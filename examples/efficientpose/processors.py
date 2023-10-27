import numpy as np
import cv2
from paz.abstract import Processor, Pose6D
import paz.processors as pr
from paz.processors.draw import (quaternion_to_rotation_matrix,
                                 project_to_image, draw_cube)
from paz.backend.boxes import compute_ious, to_corner_form

LINEMOD_CAMERA_MATRIX = np.array([
    [572.41140, 000.00000, 325.26110],
    [000.00000, 573.57043, 242.04899],
    [000.00000, 000.00000, 001.00000]],
    dtype=np.float32)


class ComputeResizingShape(Processor):
    """Computes the final size of the image to be scaled by `size`
    such that the maximum dimension of the image is equal to `size`.

    # Arguments
        size: Int, final size of maximum dimension of the image.
    """
    def __init__(self, size):
        self.size = size
        super(ComputeResizingShape, self).__init__()

    def call(self, image):
        return compute_resizing_shape(image, self.size)


def compute_resizing_shape(image, size):
    H, W = image.shape[:2]
    image_scale = size / max(H, W)
    resizing_W = int(W * image_scale)
    resizing_H = int(H * image_scale)
    resizing_shape = (resizing_W, resizing_H)
    return resizing_shape, np.array(image_scale)


class PadImage(Processor):
    """Pads the image to the final size `size`.

    # Arguments
        size: Int, final size of maximum dimension of the image.
        mode: Str, specifying the type of padding.
    """
    def __init__(self, size, mode='constant'):
        self.size = size
        self.mode = mode
        super(PadImage, self).__init__()

    def call(self, image):
        return pad_image(image, self.size, self.mode)


def pad_image(image, size, mode):
    H, W = image.shape[:2]
    pad_H = size - H
    pad_W = size - W
    pad_shape = [(0, pad_H), (0, pad_W), (0, 0)]
    image = np.pad(image, pad_shape, mode=mode)
    return image


class ComputeCameraParameter(Processor):
    """Computes camera parameter given camera matrix
    and scale normalization factor of translation.

    # Arguments
        camera_matrix: Array of shape `(3, 3)` camera matrix.
        translation_scale_norm: Float, factor to change units.
            EfficientPose internally works with meter and if the
            dataset unit is mm for example, then this parameter
            should be set to 1000.
    """
    def __init__(self, camera_matrix, translation_scale_norm):
        self.camera_matrix = camera_matrix
        self.translation_scale_norm = translation_scale_norm
        super(ComputeCameraParameter, self).__init__()

    def call(self, image_scale):
        return compute_camera_parameter(image_scale, self.camera_matrix,
                                        self.translation_scale_norm)


def compute_camera_parameter(image_scale, camera_matrix,
                             translation_scale_norm):
    camera_parameter = np.array([camera_matrix[0, 0],
                                 camera_matrix[1, 1],
                                 camera_matrix[0, 2],
                                 camera_matrix[1, 2],
                                 translation_scale_norm,
                                 image_scale])
    return camera_parameter


class RegressTranslation(Processor):
    """Applies regression offset values to translation
    anchors to get the 2D translation center-point and Tz.

    # Arguments
        translation_priors: Array of shape `(num_boxes, 3)`,
            translation anchors.
    """
    def __init__(self, translation_priors):
        self.translation_priors = translation_priors
        super(RegressTranslation, self).__init__()

    def call(self, translation_raw):
        return regress_translation(translation_raw, self.translation_priors)


def regress_translation(translation_raw, translation_priors):
    stride = translation_priors[:, -1]
    x = translation_priors[:, 0] + (translation_raw[:, :, 0] * stride)
    y = translation_priors[:, 1] + (translation_raw[:, :, 1] * stride)
    Tz = translation_raw[:, :, 2]
    translations_predicted = np.concatenate((x, y, Tz), axis=0)
    return translations_predicted.T


class ComputeTxTy(Processor):
    """Computes the Tx and Ty components of the translation vector
    with a given 2D-point and the intrinsic camera parameters.
    """
    def __init__(self):
        super(ComputeTxTy, self).__init__()

    def call(self, translation_xy_Tz, camera_parameter):
        return compute_tx_ty(translation_xy_Tz, camera_parameter)


def compute_tx_ty(translation_xy_Tz, camera_parameter):
    fx, fy = camera_parameter[0], camera_parameter[1],
    px, py = camera_parameter[2], camera_parameter[3],
    tz_scale, image_scale = camera_parameter[4], camera_parameter[5]

    x = translation_xy_Tz[:, 0] / image_scale
    y = translation_xy_Tz[:, 1] / image_scale
    tz = translation_xy_Tz[:, 2] * tz_scale

    x = x - px
    y = y - py

    tx = np.multiply(x, tz) / fx
    ty = np.multiply(y, tz) / fy

    tx, ty, tz = tx[np.newaxis, :], ty[np.newaxis, :], tz[np.newaxis, :]

    translations = np.concatenate((tx, ty, tz), axis=0)
    return translations.T


class ComputeSelectedIndices(Processor):
    """Computes row-wise intersection between two given
    arrays and returns the indices of the intersections.
    """
    def __init__(self):
        super(ComputeSelectedIndices, self).__init__()

    def call(self, box_data_raw, box_data):
        return compute_selected_indices(box_data_raw, box_data)


def compute_selected_indices(box_data_all, box_data):
    box_data_all_tuple = [tuple(row) for row in box_data_all[:, :4]]
    box_data_tuple = [tuple(row) for row in box_data[:, :4]]

    location_indices = []
    for tuple_element in box_data_tuple:
        location_index = box_data_all_tuple.index(tuple_element)
        location_indices.append(location_index)
    return np.array(location_indices)


class ToPose6D(Processor):
    """Transforms poses i.e rotations and
    translations into `Pose6D` messages.

    # Arguments
        class_names: List of class names ordered with respect to the
            class indices from the dataset ``boxes``.
        one_hot_encoded: Bool, indicating if scores are one hot vectors.
        default_score: Float, score to set.
        default_class: Str, class to set.
        box_method: Int, method to convert boxes to ``Boxes2D``.

    # Properties
        one_hot_encoded: Bool.
        box_processor: Callable.

    # Methods
        call()
    """
    def __init__(
            self, class_names=None, one_hot_encoded=False,
            default_score=1.0, default_class=None, box_method=0):
        if class_names is not None:
            arg_to_class = dict(zip(range(len(class_names)), class_names))
        self.one_hot_encoded = one_hot_encoded
        method_to_processor = {
            0: BoxesWithOneHotVectorsToPose6D(arg_to_class),
            1: BoxesToPose6D(default_score, default_class),
            2: BoxesWithClassArgToPose6D(arg_to_class, default_score)}
        self.pose_processor = method_to_processor[box_method]
        super(ToPose6D, self).__init__()

    def call(self, box_data, rotations, translations):
        return self.pose_processor(box_data, rotations, translations)


class BoxesWithOneHotVectorsToPose6D(Processor):
    """Transforms poses into `Pose6D` messages
    given boxes with scores as one hot vectors.

    # Arguments
        arg_to_class: List, of classes.

    # Properties
        arg_to_class: List.

    # Methods
        call()
    """
    def __init__(self, arg_to_class):
        self.arg_to_class = arg_to_class
        super(BoxesWithOneHotVectorsToPose6D, self).__init__()

    def call(self, box_data, rotations, translations):
        poses6D = []
        for box, rotation, translation in zip(box_data, rotations,
                                              translations):
            class_scores = box[4:]
            class_arg = np.argmax(class_scores)
            class_name = self.arg_to_class[class_arg]
            poses6D.append(Pose6D.from_rotation_vector(rotation, translation,
                                                       class_name))
        return poses6D


class BoxesToPose6D(Processor):
    """Transforms poses into `Pose6D` messages
    given no class names and score.

    # Arguments
        default_score: Float, score to set.
        default_class: Str, class to set.

    # Properties
        default_score: Float.
        default_class: Str.

    # Methods
        call()
    """
    def __init__(self, default_score=1.0, default_class=None):
        self.default_score = default_score
        self.default_class = default_class
        super(BoxesToPose6D, self).__init__()

    def call(self, box_data, rotations, translations):
        poses6D = []
        for box, rotation, translation in zip(box_data, rotations,
                                              translations):
            poses6D.append(Pose6D.from_rotation_vector(rotation, translation,
                                                       self.default_class))
        return poses6D


class BoxesWithClassArgToPose6D(Processor):
    """Transforms poses into `Pose6D` messages
    given boxes with class argument.

    # Arguments
        default_score: Float, score to set.
        arg_to_class: List, of classes.

    # Properties
        default_score: Float.
        arg_to_class: List.

    # Methods
        call()
    """
    def __init__(self, arg_to_class, default_score=1.0):
        self.default_score = default_score
        self.arg_to_class = arg_to_class
        super(BoxesWithClassArgToPose6D, self).__init__()

    def call(self, box_data, rotations, translations):
        poses6D = []
        for box, rotation, translation in zip(box_data, rotations,
                                              translations):
            class_name = self.arg_to_class[box[-1]]
            poses6D.append(Pose6D.from_rotation_vector(rotation, translation,
                                                       class_name))
        return poses6D


class DrawPose6D(pr.DrawPose6D):
    """Draws 3D bounding boxes from Pose6D messages.

    # Arguments
        object_sizes:  Array, of shape `(3,)` size of the object.
        camera_intrinsics: Array of shape `(3, 3)`,
            inrtrinsic camera parameter.
        box_color: List, the color to draw 3D bounding boxes.
    """
    def __init__(self, object_sizes, camera_intrinsics, box_color):
        self.box_color = box_color
        super().__init__(object_sizes, camera_intrinsics)

    def call(self, image, pose6D):
        if pose6D is None:
            return image
        image = draw_pose6D(image, pose6D, self.points3D, self.intrinsics,
                            self.thickness, self.box_color)
        return image


def draw_pose6D(image, pose6D, points3D, intrinsics, thickness, color):
    """Draws cube in image by projecting points3D with intrinsics
    and pose6D.

    # Arguments
        image: Array (H, W).
        pose6D: paz.abstract.Pose6D instance.
        intrinsics: Array (3, 3). Camera intrinsics for projecting
            3D rays into 2D image.
        points3D: Array (num_points, 3).
        thickness: Positive integer indicating line thickness.
        color: List, the color to draw 3D bounding boxes.

    # Returns
        Image array (H, W) with drawn inferences.
    """
    quaternion, translation = pose6D.quaternion, pose6D.translation
    rotation = quaternion_to_rotation_matrix(quaternion)
    points2D = project_to_image(rotation, translation, points3D, intrinsics)
    image = draw_cube(image, points2D.astype(np.int32),
                      thickness=thickness, color=color)
    return image


class MatchPoses(Processor):
    """Match prior boxes with ground truth poses.

    # Arguments
        prior_boxes: Numpy array of shape (num_boxes, 4).
        iou: Float in [0, 1]. Intersection over union in which prior
            boxes will be considered positive. A positive box is box
            with a class different than `background`.
    """
    def __init__(self, prior_boxes, iou=.5):
        self.prior_boxes = prior_boxes
        self.iou = iou
        super(MatchPoses, self).__init__()

    def call(self, boxes, poses):
        matched_poses = match_poses(boxes, poses, self.prior_boxes, self.iou)
        return matched_poses


def match_poses(boxes, poses, prior_boxes, iou_threshold):
    matched_poses = np.zeros((prior_boxes.shape[0], poses.shape[1] + 1))
    ious = compute_ious(boxes, to_corner_form(np.float32(prior_boxes)))
    per_prior_which_box_iou = np.max(ious, axis=0)
    per_prior_which_box_arg = np.argmax(ious, 0)
    per_box_which_prior_arg = np.argmax(ious, 1)
    per_prior_which_box_iou[per_box_which_prior_arg] = 2
    for box_arg in range(len(per_box_which_prior_arg)):
        best_prior_box_arg = per_box_which_prior_arg[box_arg]
        per_prior_which_box_arg[best_prior_box_arg] = box_arg

    matched_poses[:, :-1] = poses[per_prior_which_box_arg]
    matched_poses[per_prior_which_box_iou >= iou_threshold, -1] = 1
    return matched_poses


class TransformRotation(Processor):
    """Computes axis angle rotation vector from a rotation matrix.

    # Arguments:
        num_pose_dims: Int, number of dimensions of pose.

    # Returns:
        transformed_rotations: Array of shape (5,) containing the
            transformed rotation.
    """
    def __init__(self, num_pose_dims):
        self.num_pose_dims = num_pose_dims
        super(TransformRotation, self).__init__()

    def call(self, rotations):
        transformed_rotations = transform_rotation(rotations,
                                                   self.num_pose_dims)
        return transformed_rotations


def transform_rotation(rotations, num_pose_dims):
    final_axis_angles = []
    for rotation in rotations:
        final_axis_angle = np.zeros((num_pose_dims + 2))
        rotation_matrix = np.reshape(rotation, (num_pose_dims, num_pose_dims))
        axis_angle, jacobian = cv2.Rodrigues(rotation_matrix)
        axis_angle = np.squeeze(axis_angle) / np.pi
        final_axis_angle[:3] = axis_angle
        final_axis_angle = np.expand_dims(final_axis_angle, axis=0)
        final_axis_angles.append(final_axis_angle)
    final_axis_angles = np.concatenate(final_axis_angles, axis=0)
    return final_axis_angles


class ConcatenatePoses(Processor):
    """Concatenates rotations and translations into a single array.

    # Returns:
        poses_combined: Array of shape `(num_prior_boxes, 10)`
            containing the transformed rotation.
    """
    def __init__(self):
        super(ConcatenatePoses, self).__init__()

    def call(self, rotations, translations):
        poses_combined = concatenate_poses(rotations, translations)
        return poses_combined


def concatenate_poses(rotations, translations):
    return np.concatenate((rotations, translations), axis=-1)


class ConcatenateScale(Processor):
    """Concatenates poses with image scale into a single array.

    # Returns:
        poses_combined: Array of shape `(num_prior_boxes, 11)`
            containing the transformed rotation.
    """
    def __init__(self):
        super(ConcatenateScale, self).__init__()

    def call(self, poses, scale):
        poses_combined = concatenate_scale(poses, scale)
        return poses_combined


def concatenate_scale(poses, scale):
    scale = np.repeat(scale, poses.shape[0])
    scale = scale[np.newaxis, :]
    poses = np.concatenate((poses, scale.T), axis=1)
    return poses


class ScaleBoxes2D(Processor):
    """Scales coordinates of Boxes2D.

    # Returns:
        boxes2D: List, containg Boxes2D with scaled coordinates.
    """
    def __init__(self):
        super(ScaleBoxes2D, self).__init__()

    def call(self, boxes2D, scale):
        boxes2D = scale_boxes2D(boxes2D, scale)
        return boxes2D


def scale_boxes2D(boxes2D, scale):
    for box2D in boxes2D:
        box2D.coordinates = tuple(np.array(box2D.coordinates) * scale)
    return boxes2D


class AugmentImageAndPose(Processor):
    """Scales coordinates of Boxes2D.

    # Returns:
        boxes2D: List, containg Boxes2D with scaled coordinates.
    """
    def __init__(self, scale_min=0.7, scale_max=1.3, input_size=512):
        self.scale_min = scale_min
        self.scale_max = scale_max
        self.input_size = input_size
        super(AugmentImageAndPose, self).__init__()

    def call(self, image, boxes, rotation, translation_raw):
        boxes2D = augment_image_and_pose(image, boxes, rotation,
                                         translation_raw, self.scale_min,
                                         self.scale_max, self.input_size)
        return boxes2D


def augment_image_and_pose(image, boxes, rotation, translation_raw,
                           scale_min, scale_max, input_size):
    boxes = np.concatenate((boxes, boxes), axis=0)
    num_annotations = boxes.shape[0]
    # rotation_matrices = np.reshape(rotation, (num_annotations, 3, 3))
    scale = np.random.uniform(0, scale_max)
    angle = np.random.uniform(0, 360)

    cx = LINEMOD_CAMERA_MATRIX[0, 2]
    cy = LINEMOD_CAMERA_MATRIX[1, 2]
    H, W, _ = image.shape

    rotation_matrix = cv2.getRotationMatrix2D((cx, cy), -angle, scale)
    scaled_boxes = (boxes[:, :4] * input_size).astype(np.uint64)
    x_min = scaled_boxes[:, 0][np.newaxis, :].T
    y_min = scaled_boxes[:, 1][np.newaxis, :].T
    x_max = scaled_boxes[:, 2][np.newaxis, :].T
    y_max = scaled_boxes[:, 3][np.newaxis, :].T

    corner_1 = np.concatenate((x_min, y_min), axis=1)[np.newaxis, :]
    corner_2 = np.concatenate((x_min, y_max), axis=1)[np.newaxis, :]
    corner_3 = np.concatenate((x_max, y_max), axis=1)[np.newaxis, :]
    corner_4 = np.concatenate((x_max, y_min), axis=1)[np.newaxis, :]

    box_points = np.concatenate((corner_1, corner_2,
                                 corner_3, corner_4), axis=0)
    box_points = np.swapaxes(box_points, 0, 1)
    warped_box_points = cv2.transform(box_points, rotation_matrix)
    x_min_warped = np.min(warped_box_points[:, :, 0], axis=1)
    x_max_warped = np.max(warped_box_points[:, :, 0], axis=1)
    y_min_warped = np.min(warped_box_points[:, :, 1], axis=1)
    y_max_warped = np.max(warped_box_points[:, :, 1], axis=1)

    min_x = np.maximum(0, x_min_warped)
    max_x = np.minimum(W, x_max_warped)
    min_y = np.maximum(0, y_min_warped)
    max_y = np.minimum(H, y_max_warped)
    intersection_area = (np.maximum(0, max_x - min_x) *
                         np.maximum(0, max_y - min_y))

    augmented_img = cv2.warpAffine(image, rotation_matrix, (W, H))
    return image, boxes, rotation, translation_raw
