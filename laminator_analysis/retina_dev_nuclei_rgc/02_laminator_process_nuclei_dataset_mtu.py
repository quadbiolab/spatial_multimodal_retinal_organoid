import os
from pathlib import Path
from time import gmtime, strftime
import re
from skimage.color import rgba2rgb, rgb2gray
from multiprocessing import Pool, RawArray
import pandas as pd
from tqdm import tqdm
from skimage import io
import numpy as np

def load_mask(path):
    img = io.imread(path)
    return img

def load_images(paths):
    imgs = []
    for path in tqdm(paths):
        img = io.imread(path)
        imgs.append(img)
    imgs = np.dstack(imgs)
    return imgs

# Init worker function which creates shared variables
def init_worker(X, X_shape):
    var_dict['X'] = X
    var_dict['X_shape'] = X_shape

def setup_shared_variables():
    # Set up global variable dictionary for shared variables in the multiprocessing
    global var_dict
    var_dict = {}

def calculate_radial_profiles(df, max_radius, stack, mask, label_img):

    df['y']=np.round(df['centroid-0'].values)
    df['x']=np.round(df['centroid-1'].values)

    # Set up multiprocessing
    setup_shared_variables()
    X_shape = stack.shape
    X = RawArray('d', stack.shape[0] * stack.shape[1] * stack.shape[2])

    # Wrap as numpy array and copy data to shared array
    X_np = np.frombuffer(X).reshape(stack.shape)
    np.copyto(X_np, stack)
    # Start the process pool and do the computation
    with Pool(processes=50, initializer=init_worker, initargs=(X, X_shape)) as pool:
        result = pool.starmap(radial_profile_multi, zip(df['x'].values, df['y'].values))

    return(result)

dir_images = 'data/processed/4i/MTU_results'
dir_results = 'data/processed/4i/laminator/results_nuclei_mtu'
dir_masks = 'data/processed/4i/masks'
masks = os.listdir(dir_masks)
points = os.listdir(dir_images)

for point in points:
    print('Started laminator in nuclei mode...')
    print(strftime("%Y-%m-%d %H:%M:%S", gmtime()) + ' - Processing sample: ' + str(point))

    dir_results_point = Path(dir_results, str(point))
    Path(dir_results_point).mkdir(parents=True, exist_ok=True)

    # set directories and get paths for masks and images
    path_mask = Path(dir_masks, masks[[re.findall(r'\d+', path)[0] for path in masks].index(point)])
    dir_images_point = Path(dir_images, str(point), 'single_MTU_imgs')
    image_paths = os.listdir(dir_images_point)
    pd.DataFrame({'file':[str(path) for path in image_paths]}).reset_index().to_csv(Path(dir_results_point, 'stain_paths.csv'), index=False)

    # load nuclei dataset
    df_nuclei = pd.read_csv(
        'data/processed/4i/feature_tables/' + point + '_feature_table.csv',
        sep=' ')

    # load mask
    print(strftime("%Y-%m-%d %H:%M:%S", gmtime()) + ' - Loading images...')
    mask = load_mask(path_mask)

    # load label image
    label_img = io.imread('data/processed/4i/segmented_nuclei/'+point+'.tif')

    # load images
    stack = []
    for path in tqdm(image_paths):
        img = io.imread(path)
        img = rgb2gray(rgba2rgb(img, background=(0, 0, 0)))
        img = np.where(img > 0, 1, 0)
        stack.append(img)
    stack = np.dstack(stack)

    def radial_profile_multi(x, y, mask=mask, max_radius=500, label_img=label_img):
        center = [y, x]
        img = np.frombuffer(var_dict['X']).reshape(var_dict['X_shape'])

        y, x = np.indices(img[..., 0].shape)
        r = np.sqrt((x - center[1]) ** 2 + (y - center[0]) ** 2)
        r = r.astype(int)

        x_offset = int(center[1]) - max_radius
        y_offset = int(center[0]) - max_radius

        x_offset = np.where(x_offset < 0, np.absolute(x_offset), 0)
        y_offset = np.where(y_offset < 0, np.absolute(y_offset), 0)

        nucleus_id = label_img[int(center[0]), int(center[1])]

        # Crop image centered to point with size that keeps circle of window
        img = img[int(center[0]) - max_radius + y_offset:int(center[0]) + max_radius,
              int(center[1]) - max_radius + x_offset:int(center[1]) + max_radius, ...]
        mask = mask[int(center[0]) - max_radius + y_offset:int(center[0]) + max_radius,
               int(center[1]) - max_radius + x_offset:int(center[1]) + max_radius]
        label_img = label_img[int(center[0]) - max_radius + y_offset:int(center[0]) + max_radius,
                    int(center[1]) - max_radius + x_offset:int(center[1]) + max_radius]
        r = r[int(center[0]) - max_radius + y_offset:int(center[0]) + max_radius,
            int(center[1]) - max_radius + x_offset:int(center[1]) + max_radius]

        mask = mask * np.where(r <= max_radius, 1, 0) * np.where(label_img == nucleus_id, 0, 1)
        mask = mask.ravel()

        r = r.ravel()
        r = np.delete(r, np.where(mask == 0))
        radial_profiles = []
        for i in range(img.shape[2]):
            img_tmp = img[..., i].ravel()
            img_tmp = np.delete(img_tmp, np.where(mask == 0))
            with np.errstate(divide='ignore', invalid='ignore'):
                tbin = np.bincount(r, img_tmp)
                nr = np.bincount(r)
                radial_profiles.append(np.nan_to_num(tbin / nr))
        df = pd.DataFrame(radial_profiles).T.assign(x=int(center[1]), y=int(center[0]))
        df['position'] = df.index
        return df

    print(strftime("%Y-%m-%d %H:%M:%S", gmtime()) + ' - Calculating radial profiles...')
    results = calculate_radial_profiles(df_nuclei, 500, stack, mask, label_img)

    print(strftime("%Y-%m-%d %H:%M:%S", gmtime())+' - Saving results...')
    pd.concat(results).to_csv(Path(dir_results_point, 'df_intensity_profiles.csv'), index=False)
    print(strftime("%Y-%m-%d %H:%M:%S", gmtime())+' - Laminator analysis for sample ' + str(point) + ' completed.')
    print()
