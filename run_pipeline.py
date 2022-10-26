
import sys
sys.path.append('/home/pwahle/4i_publication_repo_2/')

import yaml 
import importlib
#load parameters
with open("/home/pwahle/4i_publication_repo_2/params.yml", 'r') as ymlfile: 
   cfg = yaml.load(ymlfile, Loader=yaml.FullLoader)

globals().update(cfg)

import modules 
from time import gmtime, strftime
import os
from pathlib import Path

wells = [43,44] # corresponds to x.tif name wells 43 and 50. Script assumes that images are numbered continuous from 0 to x.
ref_cycle = 2 #
ref_cycles = [2,7,12,17] # choose multiple if appropriate
cycles_bg = [0,6,12]

for i in wells:
    print(strftime("%Y-%m-%d %H:%M:%S", gmtime()))
    print('Processing point:',i)
    modules.simple_mask(point=i, cycle=ref_cycle,
                dir_input=data_path,
                dir_output=data_path + 'masks/',
                save=True,
                plot=False,
                show_plot=False,
                save_plot=True)


for well in wells:
    img_df = modules.get_metadata(Path(data_path,'raw_data'))
    filenames = img_df.loc[(img_df['well_id'] == well)]['file']
    
    items = []
    for i in filenames:
        items.append(Path(data_path,'aligned', i)) 
        
    if not (all(os.path.isfile(i) for i in items)):
        modules.run_elastix(point = well,
                    ref_cycles = ref_cycles,
                    dir_mask = Path(data_path,'masks'),
                    dir_input = Path(data_path,'raw_data'),
                    dir_output = Path(data_path,'aligned'))
    else:
        print('well ' + str(well) + ' already aligned')

for well in wells:
    modules.denoise_well(well = well)
    
    
for well in wells:
    modules.refine_mask(well = well)
    
for well in wells:
    img_df = modules.get_metadata(Path(data_path,'denoised'))
    filenames = img_df.loc[(img_df['well_id'] == well)]['file']
    
    items = []
    for i in filenames:
        items.append(Path(data_path,'bg_subtracted', i)) 
        
    if not (all(os.path.isfile(i) for i in items)):
        modules.bg_subtraction(well = well,
                        dir_input=Path(data_path,'denoised'),
                        dir_masks=Path(data_path,'masks'),
                        dir_output=Path(data_path,'bg_subtracted'),
                        cycles_bg=[0, 6, 12],
                        cycle_hoechst = 1)
    
for well in wells:
    modules.segment_nuclei(well = well, 
                           ref_cycle = 0, 
                           dir_input = Path(data_path, 'denoised'), 
                           dir_output = Path(data_path, 'segmented_nuclei'))
   
for well in wells:
    modules.generate_pixel_matrices(well = well,
                         dir_input = Path(data_path,"bg_subtracted"),
                         dir_output = Path(data_path,'pixel_matrices/'),
                         cycles_bg = cycles_bg,
                         to_collagen_mask = to_collagen_mask,
                         mask_collagen = False,
                         overwrite_denoised_images_with_collagen_masked_images = False)

conditions = {'week39' : [43,44]}
for condition in conditions:
    modules.run_matrix_normalization(wells, 
                             dir_input = Path(data_path, 'pixel_matrices'),
                             dir_output = Path(data_path,'pixel_matrices'), 
                             fusion_matrix = True)
    
print('run fSOM.R script now.')

answer = input('once fSOM.R was run please type [y] to continue.')

if answer == 'y':
    for well in wells:
        modules.MTU_assignment(well = well, 
                       k = 20, 
                       dir_matrix = Path(data_path, 'pixel_matrices'),
                       dir_output = Path(data_path, 'MTU_results'),
                       dir_fSOM = Path(data_path, 'fSOM_output'))
else:
    print('MTUs cannot be generated without the fSOM_output/som_codes.npz file.')