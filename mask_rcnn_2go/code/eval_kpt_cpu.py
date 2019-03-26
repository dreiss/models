from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import logging
import os
import sys
import multiprocessing

import cv2  # NOQA (Must import before importing caffe2 due to bug in cv2)
import infer_model_pb_utils as infer_pb_utils
import model_utils
from caffe2.python import workspace
from json_dataset import JsonDataset
from json_dataset_evaluator import evaluate_boxes, evaluate_masks, evaluate_keypoints
from test_engine import (
    empty_results,
    extend_results,
    #extend_results_with_classes,
    #extend_seg_results_with_classes,
)


FORMAT = "%(levelname)s %(filename)s:%(lineno)4d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, stream=sys.stdout)
logger = logging.getLogger(__name__)


cv2.ocl.setUseOpenCL(False)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--net", dest="net", help="pb net path", default=None, type=str)
    parser.add_argument(
        "--init_net", dest="init_net", help="pb init net path", default=None, type=str
    )
    parser.add_argument(
        "--dataset", type=str, required=True, help="Name of the test JsonDataset"
    )
    parser.add_argument(
        "--dataset_dir", type=str, required=True, help="Dataet image path"
    )
    parser.add_argument(
        "--dataset_ann", type=str, required=True, help="Dataet annotation file"
    )
    parser.add_argument(
        "--output_dir", type=str, default="/tmp/", help="Output dir for eval results"
    )
    parser.add_argument(
        "--min_size",
        type=int,
        default=320,
        help="Target size for min side while resizing",
    )
    parser.add_argument(
        "--max_size",
        type=int,
        default=640,
        help="Target size for max side while resizing",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=0,
        help="Run evaluation in parallel when 1",
    )
    ret = parser.parse_args()
    ret.output_dir = os.path.abspath(ret.output_dir)
    return ret


def load_model(args):
    net, _ = model_utils.load_model_pb(
        args.net, args.init_net
    )
    return net


def run_single_image(net, fname, target_min_size, target_max_size):
    image = cv2.imread(fname)
    if image is None:
        return None

    ret = infer_pb_utils.run_single_kpts(
        net,
        image,
        target_size=target_min_size,
        max_size=target_max_size,
        pixel_means=None,
        pixel_stds=None,
    )
    return ret


RUN_ARGS = None


def _run_args_init(run_args):
    global RUN_ARGS
    RUN_ARGS = run_args


def _run_single_entry(entry):
    return run_single_image(
        fname=entry['image'],
        **RUN_ARGS
    )


def eval_kpts_cpu(args, net):
    # load dataset
    ds = JsonDataset(args.dataset, args.dataset_dir, args.dataset_ann)
    roidb = ds.get_roidb()
    logger.warning("Loaded dataset {} with {} images".format(args.dataset, len(roidb)))

    # initialize result
    all_results = empty_results(ds.num_classes, len(roidb))
    all_boxes = all_results["all_boxes"]
    all_keyps = all_results["all_keyps"]

    # run model
    for i, entry in enumerate(roidb):
        # Uncomment to only push the street corner image
        #if entry["id"] != 8211:
        #    continue
        #print()
        #print(entry["image"])
        #print()
        if i % 10 == 0:
            logger.warning("{}/{}".format(i, len(roidb)))
        ret = run_single_image(
            net,
            entry["image"],
            target_min_size=args.min_size,
            target_max_size=args.max_size,
        )
        boxes, xy_preds, classids = ret
        extend_results(i, all_boxes, [[], boxes])
        extend_results(i, all_keyps, [[], xy_preds])

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # evaluate results
    logger.info("Evaluating detections")
    evaluate_boxes(ds, all_boxes, args.output_dir, use_salt=False)

    logger.info("Evaluating keypoints")
    evaluate_keypoints(ds, all_boxes, all_keyps, args.output_dir, use_salt=False)


def main():
    args = parse_args()

    num_threads = 8 if not args.parallel else 1
    workspace.GlobalInit(
        [
            "caffe2",
            "--caffe2_log_level=2",
            "--caffe2_omp_num_threads={}".format(num_threads),
            "--caffe2_mkl_num_threads={}".format(num_threads),
        ]
    )

    net = load_model(args)
    eval_kpts_cpu(args, net)


if __name__ == "__main__":
    main()
