import argparse
from efficientdet_model import EfficientDet
from misc import raw_images, load_pretrained_weights, preprocess_images
from postprocess import get_postprocessor


if __name__ == "__main__":

    description = "Build EfficientDet model"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-m",
        "--model_name",
        default="efficientdetd0",
        type=str,
        help="EfficientDet model name",
        required=False,
    )
    parser.add_argument(
        "-b",
        "--backbone_name",
        default="efficientnet-b0",
        type=str,
        help="EfficientNet backbone name",
        required=False,
    )
    parser.add_argument(
        "-bw",
        "--backbone_weight",
        default="imagenet",
        type=str,
        help="EfficientNet backbone weight",
        required=False,
    )
    parser.add_argument(
        "-a",
        "--act_type",
        default="swish",
        type=str,
        help="Activation function",
        required=False,
    )
    parser.add_argument(
        "--min_level",
        default=3,
        type=int,
        help="EfficientNet feature minimum level. "
        "Level decides the activation map size, "
        "eg: For an input image of 640 x 640, "
        "the activation map resolution at level 3 is "
        "(640 / (2 ^ 3)) x (640 / (2 ^ 3))",
        required=False,
    )
    parser.add_argument(
        "--max_level",
        default=7,
        type=int,
        help="EfficientNet feature maximum level. "
        "Level decides the activation map size,"
        " eg: For an input image of 640 x 640, "
        "the activation map resolution at level 3 is"
        " (640 / (2 ^ 3)) x (640 / (2 ^ 3))",
        required=False,
    )
    parser.add_argument(
        "--fpn_name",
        default="BiFPN",
        type=str,
        help="Feature Pyramid Network name",
        required=False,
    )
    parser.add_argument(
        "--fpn_weight_method",
        default="fastattn",
        type=str,
        help="FPN weight method to fuse features. "
             "Options available: attn, fastattn",
        required=False,
    )
    parser.add_argument(
        "--fpn_num_filters",
        default=64,
        type=int,
        help="Number of filters at the FPN convolutions",
        required=False,
    )
    parser.add_argument(
        "--fpn_cell_repeats",
        default=3,
        type=int,
        help="Number of FPNs repeated in the FPN layer",
        required=False,
    )
    parser.add_argument(
        "--use_batchnorm_for_sampling",
        default=True,
        type=bool,
        help="Flag to apply batch normalization after resampling features",
        required=False,
    )
    parser.add_argument(
        "--conv_after_downsample",
        default=False,
        type=bool,
        help="Flag to apply convolution after downsampling features",
        required=False,
    )
    parser.add_argument(
        "--conv_batchnorm_act_pattern",
        default=False,
        type=bool,
        help="Flag to apply convolution, batch normalization and activation",
        required=False,
    )
    parser.add_argument(
        "--separable_conv",
        default=True,
        type=bool,
        help="Flag to use separable convolutions",
        required=False,
    )
    parser.add_argument(
        "--aspect_ratios",
        default=[1.0, 2.0, 0.5],
        type=list,
        action='append',
        help="Aspect ratio of the boxes",
        required=False,
    )
    parser.add_argument(
        "--survival_prob",
        default=None,
        type=float,
        help="Survival probability for drop connect",
        required=False,
    )
    parser.add_argument(
        "--num_classes",
        default=90,
        type=int,
        help="Number of classes in the dataset",
        required=False,
    )
    parser.add_argument(
        "--num_scales",
        default=3,
        type=int,
        help="Number of scales for the boxes",
        required=False,
    )
    parser.add_argument(
        "--anchor_scale",
        default=4,
        type=int,
        help="Number of anchor scales available",
        required=False,
    )
    parser.add_argument(
        "--image_size",
        default=512,
        type=int,
        help="Image size",
        required=False,
    )
    parser.add_argument(
        "--box_class_repeats",
        default=3,
        type=int,
        help="Number of repeated blocks in box and class net",
        required=False,
    )
    parser.add_argument(
        "--feature_only",
        default=False,
        type=bool,
        help="Whether feature only is required from EfficientDet",
        required=False,
    )
    parser.add_argument(
        "--postprocessor",
        default='paz',
        type=str,
        help="Which postprocessor to use. "
             "Options: paz, pre_class_official, global_official",
        required=False,
    )
    parser.add_argument(
        "--weight_file_path",
        default='/media/deepan/externaldrive1/Gini/project_repos/paz/'
                'examples/efficientdet/efficientdet-d0.h5',
        type=str,
        help="EfficientDet model weight file path. "
             "Options: paz, pre_class_official, global_official",
        required=False,
    )

    args = parser.parse_args()
    config = vars(args)
    print(config)
    model = EfficientDet(config=config)
    model.build(raw_images.shape)
    print(model.summary())

    model = load_pretrained_weights(model, config['weight_file_path'])
    print('Successfully copied weights.')

    image_size = (raw_images.shape[0],
                  config['image_size'],
                  config['image_size'],
                  raw_images.shape[-1])
    input_image, image_scales = preprocess_images(raw_images, image_size)
    class_out, box_out = model(input_image)
    postprocess_detections = get_postprocessor(config['postprocessor'])
    detections = postprocess_detections(config,
                                        class_out,
                                        box_out,
                                        image_scales,
                                        raw_images=raw_images)
    print(detections)
    print('task completed')
