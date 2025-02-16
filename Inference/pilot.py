import numpy as np
import os
import sys
from tqdm import tqdm
import random
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, TensorDataset, ConcatDataset
import glob
import imageio
import ntpath
import cv2
import argparse

# MotionBERT imports
from utils.loader import *
from utils.tools import *
from utils.learning import *
from utils import ActionNet
from collections import Counter
from scipy.stats import mode
from utils.utils_data import flip_data
from utils.dataset_wild import WildDetDataset
from utils.vismo import render_and_save

# Alphapose imports
import json
from alphapose_args import *
from utils.alphapose_loader import VideoLoader, DetectionLoader, DetectionProcessor, DataWriter, Mscoco
from utils.alphapose_util import write_results, dynamic_write_results
from models.SPPE.src.main_fast_inference import *
from utils.pPose_nms import pose_nms, write_json
from utils.fn import getTime


def alphapose(videofile):
    args =  opt
    args.dataset = 'halpe'

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Using device: {device}')

    if not args.sp:
        torch.multiprocessing.set_start_method('forkserver', force=True)
        torch.multiprocessing.set_sharing_strategy('file_system')
    mode = args.mode
    if not os.path.exists(args.outputpath):
        os.mkdir(args.outputpath)
    
    if not len(videofile):
        raise IOError('Error: must contain --video')

    # Load input video
    data_loader = VideoLoader(videofile, batchSize=args.detbatch).start()
    (fourcc,fps,frameSize) = data_loader.videoinfo()

    # Load detection loader
    print('Loading YOLO model..')
    sys.stdout.flush()
    det_loader = DetectionLoader(data_loader, batchSize=args.detbatch).start()
    det_processor = DetectionProcessor(det_loader).start()
    
    # Load pose model
    pose_dataset = Mscoco()
    if args.fast_inference:
        pose_model = InferenNet_fast(4 * 1 + 1, pose_dataset)
    else:
        pose_model = InferenNet(4 * 1 + 1, pose_dataset)

    pose_model = pose_model.to(device)
    pose_model.eval()

    runtime_profile = {
        'dt': [],
        'pt': [],
        'pn': []
    }

    # Data writer
    save_path = os.path.join(args.outputpath, 'AlphaPose_'+ntpath.basename(videofile).split('.')[0]+'.avi')
    writer = DataWriter(args.save_video, save_path, cv2.VideoWriter_fourcc(*'XVID'), fps, frameSize).start()

    im_names_desc =  tqdm(range(data_loader.length()))
    batchSize = args.posebatch
    for i in im_names_desc:
        start_time = getTime()
        with torch.no_grad():
            (inps, orig_img, im_name, boxes, scores, pt1, pt2) = det_processor.read()
            if orig_img is None:
                break
            if boxes is None or boxes.nelement() == 0:
                writer.save(None, None, None, None, None, orig_img, im_name.split('/')[-1])
                continue

            ckpt_time, det_time = getTime(start_time)
            runtime_profile['dt'].append(det_time)
            # Pose Estimation
            
            datalen = inps.size(0)
            leftover = 0
            if (datalen) % batchSize:
                leftover = 1
            num_batches = datalen // batchSize + leftover
            hm = []
            for j in range(num_batches):
                inps_j = inps[j*batchSize:min((j +  1)*batchSize, datalen)]
                inps_j = inps_j.to(device)

                hm_j = pose_model(inps_j)
                hm.append(hm_j)
            hm = torch.cat(hm)
            ckpt_time, pose_time = getTime(ckpt_time)
            runtime_profile['pt'].append(pose_time)

            hm = hm.cpu().data
            writer.save(boxes, scores, hm, pt1, pt2, orig_img, im_name.split('/')[-1])
            ckpt_time, post_time = getTime(ckpt_time)
            runtime_profile['pn'].append(post_time)

        if args.profile:
            # TQDM
            im_names_desc.set_description(
            'det time: {dt:.3f} | pose time: {pt:.2f} | post processing: {pn:.4f}'.format(
                dt=np.mean(runtime_profile['dt']), pt=np.mean(runtime_profile['pt']), pn=np.mean(runtime_profile['pn']))
            )

    print('===========================> Finish Model Running.')
    if (args.save_img or args.save_video) and not args.vis_fast:
        print('===========================> Rendering remaining images in the queue...')
        print('===========================> If this step takes too long, you can enable the --vis_fast flag to use fast rendering (real-time).')
    while(writer.running()):
        pass
    writer.stop()
    final_result = writer.results()
    write_json(final_result, args.outputpath)
    return args.outputpath

def alphapose_mod(videofile):
    args = opt
    args.dataset = 'halpe'
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Using device: {device}')

    # Optimize CUDA operations
    torch.backends.cudnn.benchmark = True
    
    if not args.sp:
        torch.multiprocessing.set_start_method('forkserver', force=True)
        torch.multiprocessing.set_sharing_strategy('file_system')
        
    # Increase batch sizes for better GPU utilization
    args.detbatch = max(args.detbatch, 4)
    args.posebatch = max(args.posebatch, 4)
    
    if not os.path.exists(args.outputpath):
        os.mkdir(args.outputpath)
    
    if not len(videofile):
        raise IOError('Error: must contain --video')

    data_loader = VideoLoader(videofile, batchSize=args.detbatch).start()
    (fourcc, fps, frameSize) = data_loader.videoinfo()

    print('Loading YOLO model..')
    sys.stdout.flush()
    det_loader = DetectionLoader(data_loader, batchSize=args.detbatch).start()
    det_processor = DetectionProcessor(det_loader).start()
    
    # Load pose model and move to GPU immediately
    pose_dataset = Mscoco()
    pose_model = InferenNet_fast(4 * 1 + 1, pose_dataset) if args.fast_inference else InferenNet(4 * 1 + 1, pose_dataset)
    pose_model = pose_model.to(device)
    pose_model.eval()

    save_path = os.path.join(args.outputpath, 'AlphaPose_'+ntpath.basename(videofile).split('.')[0]+'.avi')
    writer = DataWriter(args.save_video, save_path, cv2.VideoWriter_fourcc(*'XVID'), fps, frameSize).start()

    im_names_desc = tqdm(range(data_loader.length()))
    batchSize = args.posebatch
    
    for i in im_names_desc:
        with torch.no_grad():  # Removed autocast for now
            (inps, orig_img, im_name, boxes, scores, pt1, pt2) = det_processor.read()
            if orig_img is None:
                break
            if boxes is None or boxes.nelement() == 0:
                writer.save(None, None, None, None, None, orig_img, im_name.split('/')[-1])
                continue

            # Process larger batches at once
            datalen = inps.size(0)
            num_batches = (datalen + batchSize - 1) // batchSize
            
            # Process batches more efficiently
            hm = []
            for j in range(num_batches):
                start_idx = j * batchSize
                end_idx = min((j + 1) * batchSize, datalen)
                inps_j = inps[start_idx:end_idx].to(device, non_blocking=True)
                
                # Run pose estimation
                hm_j = pose_model(inps_j)
                if hm_j.dtype != torch.float32:
                    hm_j = hm_j.float()
                hm.append(hm_j)

            # Concatenate results on GPU
            hm = torch.cat(hm) if len(hm) > 1 else hm[0]
            
            # Ensure float32 dtype before moving to CPU
            if hm.dtype != torch.float32:
                hm = hm.float()
            
            # Move to CPU
            hm = hm.cpu()
            
            # Save results
            writer.save(boxes, scores, hm, pt1, pt2, orig_img, im_name.split('/')[-1])

    print('===========================> Finish Model Running.')
    writer.stop()
    final_result = writer.results()
    write_json(final_result, args.outputpath)
    return args.outputpath


def create_pose_data(json_path, out_path):
    testloader_params = {
        'batch_size': 1,
        'shuffle': False,
        'num_workers': 8,
        'pin_memory': True,
        'prefetch_factor': 4,
        'persistent_workers': True,
        'drop_last': False
    }
    os.makedirs(out_path, exist_ok=True)
    for file in glob.glob(str(json_path)+"*.json"):
        fname = file.split("/")[-1]
        # Keep relative scale with pixel coornidates
        wild_dataset = WildDetDataset(file, out_path, clip_len=243, scale_range=[1,1], focus=None)

        test_loader = DataLoader(wild_dataset, **testloader_params)

        results_all = []
        with torch.no_grad():
            for batch_input in tqdm(test_loader):
                feat = batch_input
                results_all.append(feat.cpu().numpy())

    results_all = np.hstack(results_all)
    results_all = np.concatenate(results_all)
    np.save('%s/%s.npy' % (out_path, fname[:-5]), results_all)


def load_state_dict_cpu_fix(model, state_dict):
    # Create new OrderedDict without 'module.' prefix
    from collections import OrderedDict
    new_state_dict = OrderedDict()
    for k, v in state_dict.items():
        if k.startswith('module.'):
            name = k[7:]  # remove 'module.' prefix
        else:
            name = k
        new_state_dict[name] = v
    # Load the new state dict
    model.load_state_dict(new_state_dict, strict=True)
    return model

def inference(data, args, task):
    checkpoint = './models'
    model_backbone = load_backbone(args)
    if task == "classification":
        model = ActionNet.ActionNet(backbone=model_backbone, dim_rep=args.dim_rep, num_classes=args.action_classes, dropout_ratio=args.dropout_ratio, version=args.model_version, hidden_dim=args.hidden_dim, num_joints=args.num_joints)
        chk_path = os.path.join(checkpoint, f'class_model.bin')
    else: # regression
        chk_path = os.path.join(checkpoint, f'reg_model.bin')
        model = model_backbone
        joint_mask = torch.tensor([1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1], dtype=torch.float32)
        joint_mask = joint_mask.view(1, -1, 1).cpu()
        all_predictions = []

    # First move model to CUDA if available
    if torch.cuda.is_available():
        model = model.cuda()
        # Then wrap in DataParallel
        model = nn.DataParallel(model) if not isinstance(model, nn.DataParallel) else model
    
    checkpoint = torch.load(chk_path, map_location=lambda storage, loc: storage, weights_only=False)

    model.eval()

    if torch.cuda.is_available():    
        # Now load the state dict
        if 'module.' in list(checkpoint['model'].keys())[0]:
            # If checkpoint was saved with DataParallel
            model.load_state_dict(checkpoint['model'])
        else:
            # If checkpoint was saved without DataParallel
            model.module.load_state_dict(checkpoint['model'])
    else:
        model = load_state_dict_cpu_fix(model, checkpoint['model'])

    window_preds = torch.zeros(0, dtype=torch.long, device='cpu')

    data = tqdm(data, desc="Testing")
    with torch.no_grad():
        for id, batch_input in enumerate(data):
            data.set_postfix({"Batch": id})
            batch_size = len(batch_input)
            batch_input = batch_input.float()
            if torch.cuda.is_available():
                batch_input = batch_input.cuda()
                

            predictions = model(batch_input) # ~15s for class batch

            if task == "classification":
                predicted = predictions.argmax(dim=1).cpu()
                window_preds = torch.cat([window_preds, predicted.view(-1)])
            else:
                predictions = predictions.cpu() * joint_mask
                predictions_np = predictions.cpu().numpy()
                all_predictions.append(predictions_np)

    if task == "classification":
        frame_predictions = window_preds.numpy().tolist()
        class_labels = smooth_predictions(frame_predictions)
        model_output = [int(x) for x in class_labels]
    else:
        print(all_predictions)
        print("all_predictions")
        model_output = np.vstack(all_predictions)  # Flatten along batch axis
    return model_output

def get_exercise_outcomes(class_labels, joint_data, subject_id, session_id, output_folder):
    """
    Computes and saves exercise outcomes into a JSON file.

    Parameters:
        class_labels (list): Frame-by-frame labels for exercises.
        joint_data (np.ndarray): Predicted joint data for motion variability computation.
        subject_id (str): Unique identifier for the subject.
        session_id (str): Unique identifier for the session.
        output_folder (str): Path to the JSON file where outcomes will be saved.

    Returns:
        None
    """
    # Compute metrics
    exercise_duration = compute_dur(class_labels)  # in minutes
    rep_count, rep_ids = compute_rep_count(class_labels)
    motion_variability = compute_mad(joint_data, rep_ids, rep_count)

    exercise_duration = {k: float(v) for k, v in exercise_duration.items()}
    rep_count = {k: int(v) for k, v in rep_count.items()}
    motion_variability = {k: [float(val) for val in v] for k, v in motion_variability.items()}

    # Create a dictionary to store all outcomes
    outcomes = {
        "subject_id": subject_id,
        "session_id": session_id,
        "exercise_outcomes": {
            "exercise_duration": exercise_duration,
            "repetition_count": rep_count,
            "motion_variability": motion_variability
        }
    }

    output_file = os.path.join(output_folder, f"{subject_id}_session{session_id}_outcomes.json")
    # Save to a JSON file
    with open(output_file, 'w') as f:
        json.dump(outcomes, f, indent=4)

    print(f"Outcomes successfully saved to {output_file}")

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Exercise Analysis Pipeline')
    parser.add_argument('--subject_id', type=str, default='subject3',
                      help='Subject ID (default: subject3)')
    parser.add_argument('--session_id', type=str, default='0',
                      help='Session ID (default: 0)')
    parser.add_argument('--video', type=str, 
                      default='./demo/Exercise_Elderly_Trim.mp4',
                      help='Path to video file (default: ./demo/Exercise_Elderly_Trim.mp4)')
    
    os.chdir(sys.path[0])
    args_class = get_config("./configs/class.yaml")
    args_reg = get_config("./configs/reg.yaml")
    output_folder = "./exercise_outcomes"
    os.makedirs(output_folder, exist_ok=True)

    # Parse command-line arguments
    cli_args = parser.parse_args()
    subject_id = cli_args.subject_id
    session_id = cli_args.session_id
    videofile = cli_args.video

    json_pose_path = alphapose_mod(videofile) # extracts the AlphaPose json output
    npy_pose_path = './motionbert/results_test_pose/demo/' # output path for saving the npy pose file
    create_pose_data(json_pose_path, npy_pose_path) # converts the AlphaPose 2D pose into a human-centric 2D pose saved in npy

    # Load human-centric 2D pose data from saved npy file 
    # test variable is load the demo files or not 
    data_class = create_dataloader(['patient3'], 243, 1, test=True, task="classification", batch_size=32, shuffle=False)
    data_reg = create_dataloader(['patient3'], 243, 243, test=True, task="regression", batch_size=2, shuffle=False)

    # Inference
    class_labels = inference(data_class, args_class, 'classification')
    joint_data = inference(data_reg, args_reg, 'regression')
    get_exercise_outcomes(class_labels, joint_data, subject_id, session_id, output_folder)
