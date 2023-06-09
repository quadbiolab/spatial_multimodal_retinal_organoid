#  Laminator - oriented-sliding-window analysis
import numpy as np
import pandas as pd
from skimage import io
from skimage import measure
from skimage.filters import gaussian, threshold_otsu
from scipy.ndimage import distance_transform_edt
from scipy import optimize
import matplotlib.pyplot as plt
from math import cos, sin, radians
from skimage.transform import rotate
from multiprocessing import Pool, RawArray
from functools import partial
from tqdm import tqdm


def scale_image(image, percentile=1):
    image = np.interp(image, (np.percentile(image, percentile), np.percentile(image, 100 - percentile)), (0, +65535))
    return image


def load_mask(path):
    """
    Load mask
    Args:
        path: (string) path to mask image

    Returns:
        img: binary numpy array of the loaded mask
    """
    img = io.imread(path)
    return img


def load_images(paths):
    """
    Load images
    Args:
        paths: (string) paths to images

    Returns:
        imgs: stack of all images specified
    """
    imgs = []
    for path in tqdm(paths):
        img = io.imread(path)
        imgs.append(img)
    imgs = np.dstack(imgs)
    return imgs


def prepare_images(imgs, scale=True, percentile=1, log_transform=False):
    """
    Prepare images for analysis by applying scaling and/or log-transform
    Args:
        imgs:
        scale:
        percentile:
        log_transform:

    Returns:

    """
    if scale:
        imgs = np.apply_over_axes(scale_image, imgs, 2)
    if log_transform:
        imgs = np.log(imgs + 1)
    return imgs


def get_contour(mask, smoothing=True, sigma=50):
    """
    Get contours of mask
    Args:
        mask: (array) binary mask
        smoothing: (logical) apply smoothing
        sigma: (int) sigma for smoothing

    Returns:
         contours: pandas dataframe
    """
    # Smooth mask outline
    if smoothing:
        mask = gaussian(mask, sigma=sigma)
        thr = threshold_otsu(mask)
        mask = (mask > thr).astype(int)

    # Find contours
    contours = measure.find_contours(mask, 0.5)
    results = []
    for i, contour in enumerate(contours):
        results.append(contour.round().astype(int))

    df = []
    for i in range(len(results)):
        df_tmp = pd.DataFrame(results[i]).assign(contour=i).drop_duplicates()
        df_tmp['position'] = df_tmp.index
        df.append(df_tmp)

    df = pd.concat(df).rename(columns={0: 'y', 1: 'x'})
    return df


def assess_rotation(angle, img, window_size, slice_width, scale=(10, 2)):
    """
    Assess rotation by integration of the selected euclidean distance transform of the mask image
    Args:
        angle:
        img:
        window_size:
        slice_width:
        scale:

    Returns:
    """
    range_y = round(window_size / scale[0]) + window_size
    range_x = round(slice_width / scale[1])
    rotated_img = rotate(img, angle)

    return rotated_img[window_size:range_y, window_size - range_x:window_size + range_x].sum() * (-1)


def distance_transform(mask, smoothing=True, sigma=25):
    """
    Apply euclidean distance transform to image
    Args:
        mask: (array) binary mask image
        smoothing: (logical) apply gaussian after transformation
        sigma: (int) sigma of gaussian

    Returns:
        distance_img: (array) distance transform
    """

    distance_img = distance_transform_edt(mask)
    if smoothing:
        distance_img = gaussian(distance_img, sigma=sigma)
    return distance_img


def get_angle(x, y, position, contour, distance_transform, window_size, slice_width):
    """
    Optimize assess_rotation() for a given position, distance transform and window_size
    Args:
        x (int):
        y (int):
        distance_transform: (array)
        window_size (int):
        slice_width (int):

    Returns:
        angle: (int) angle in degree
    """

    # Get boundaries of wedge_area on original image
    x_offset = x - window_size
    y_offset = y - window_size

    x_offset = np.where(x_offset < 0, np.absolute(x_offset), 0)
    y_offset = np.where(y_offset < 0, np.absolute(y_offset), 0)

    # Crop image centered to point with size that keeps circle of window
    cropped = distance_transform[y - window_size + y_offset:y + window_size, x - window_size + x_offset:x + window_size]

    padded = np.zeros([2 * window_size, 2 * window_size])
    padded[y_offset:cropped.shape[0] + y_offset, x_offset:cropped.shape[1] + x_offset] = cropped

    # Optimize rotation of cropped image for half of the window by summing the corresponding area of the distance image
    res = optimize.minimize(assess_rotation, x0=0, args=(padded, window_size, slice_width),
                            bounds=[(-180, 180)])
    angle = res['x']
    df_angle = pd.DataFrame().assign(angle=angle, x=x, y=y, window_size=window_size,
                                     slice_width=slice_width, x_offset=x_offset, y_offset=y_offset, position=position,
                                     contour=contour)
    return df_angle


def calculate_angles(contours, distance_transform, window_size, slice_width, sample_rate=100):
    """
    Get angles for all positions in the contours dataframe
    Args:
        contours:
        distance_transform:
        window_size:
        slice_width:

    Returns:

    """
    contours = contours.iloc[::sample_rate, :]

    # Start the process pool and do the computation
    with Pool(processes=25) as pool:
        get_angle_partial = partial(get_angle, distance_transform=distance_transform, window_size=window_size,
                                    slice_width=slice_width)
        result = pool.starmap(get_angle_partial,
                              zip(contours['x'].values, contours['y'].values, contours['position'].values,
                                  contours['contour'].values))
    result = pd.concat(result)

    result = result.assign(window=range(0, len(result)))
    return result


def assess_oriented_windows(contours, img, show_angles, show_plot=True, save_plot=False, file=None, arrow_radius=100):
    # Plot contour on original image
    fig, ax = plt.subplots(figsize=(20, 20))
    ax.imshow(img, cmap=plt.cm.gray)

    if show_angles:
        r = arrow_radius
        for index, row in contours.iterrows():
            ax.arrow(row['x'], row['y'], r * cos(radians(row['angle'] + 90)),
                     r * sin(radians(row['angle'] + 90)), color='blue')

    ax.scatter(contours['x'].values, contours['y'].values, c='red')
    ax.axis('image')
    ax.set_xticks([])
    ax.set_yticks([])
    if save_plot:
        plt.savefig(str(file + '.png'))
    if show_plot:
        plt.show()
    plt.close('all')


def create_slice_stack(df_meta, img):
    positions = df_meta['position'].values
    slices = []
    for i in positions:
        df_tmp = df_meta[df_meta['position'] == i]
        slice_positioned = retrieve_slice(df_tmp, img)
        slices.append(slice_positioned)
    slices = np.dstack(slices)
    return slices


def retrieve_slice(df_tmp, img):
    window_size = df_tmp['window_size'].values[0]
    slice_width = df_tmp['slice_width'].values[0]
    angle = df_tmp['angle'].values[0]
    x = df_tmp['x'].values[0]
    y = df_tmp['y'].values[0]
    slice = np.zeros([2 * window_size, 2 * window_size])
    slice[window_size:, window_size - slice_width:window_size + slice_width] = 1
    slice = rotate(slice, -angle)
    slice_positioned = np.zeros(img.shape)
    x_min = int(np.array([(x - window_size) * -1 if (x - window_size) < 0 else 0]).astype(int))
    x_max = int(np.array([slice.shape[1] - (x + window_size - img.shape[1]) if (x + window_size) > img.shape[1] else
                          slice.shape[1]]).astype(int))
    y_min = int(np.array([(y - window_size) * -1 if (y - window_size) < 0 else 0]).astype(int))
    y_max = int(np.array([slice.shape[0] - (y + window_size - img.shape[0]) if (y + window_size) > img.shape[0] else
                          slice.shape[0]]).astype(int))
    slice = slice[y_min:y_max, x_min:x_max]
    slice_positioned[y - window_size + y_min:y + window_size, x - window_size + x_min:x + window_size] = slice
    slice_positioned = np.where(slice_positioned > 0, 1, 0)
    return slice_positioned


def rotate_slice(angle, x, y, x_offset, y_offset, window_size, slice_width):
    """

    Args:
        angle:
        x:
        y:
        x_offset:
        y_offset:
        window_size:
        slice_width:

    Returns:

    """
    stack = np.frombuffer(var_dict['X']).reshape(var_dict['X_shape'])
    # Crop image centered to point with size that keeps circle of window
    stack_cropped = stack[y - window_size + y_offset:y + window_size, x - window_size + x_offset:x + window_size, ...]
    stack_padded = np.zeros([2 * window_size, 2 * window_size, stack.shape[2]])
    stack_padded[y_offset:stack_cropped.shape[0] + y_offset, x_offset:stack_cropped.shape[1] + x_offset,
    ...] = stack_cropped

    # Apply rotation to original cropped image
    stack_rotated = rotate(stack_padded, angle)[window_size:, window_size - slice_width:window_size + slice_width, ...]
    stack_rotated = np.average(stack_rotated, axis=1)

    return stack_rotated


# Init worker function which creates shared variables
def init_worker(X, X_shape):
    var_dict['X'] = X
    var_dict['X_shape'] = X_shape


def setup_shared_variables():
    # Set up global variable dictionary for shared variables in the multiprocessing
    global var_dict
    var_dict = {}


def rotate_slices(df, stack):
    # Set up multiprocessing
    setup_shared_variables()
    X_shape = stack.shape
    X = RawArray('d', stack.shape[0] * stack.shape[1] * stack.shape[2])

    # Wrap as numpy array and copy data to shared array
    X_np = np.frombuffer(X).reshape(stack.shape)
    np.copyto(X_np, stack)

    # Start the process pool and do the computation
    with Pool(processes=25, initializer=init_worker, initargs=(X, X_shape)) as pool:
        result = pool.starmap(rotate_slice, zip(df['angle'].values,
                                                df['x'].values,
                                                df['y'].values,
                                                df['x_offset'].values,
                                                df['y_offset'].values,
                                                df['window_size'].values,
                                                df['slice_width'].values))

    # Assemble results into numpy stack
    results = np.dstack(result)

    # Convert to pandas dataframe
    names = ['radial_position', 'stain', 'window']
    index = pd.MultiIndex.from_product([range(s) for s in results.shape], names=names)
    df_results = pd.DataFrame({'intensity': results.flatten()}, index=index)['intensity'].reset_index()

    return df_results
