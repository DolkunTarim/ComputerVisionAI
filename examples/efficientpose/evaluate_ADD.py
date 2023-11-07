import os
import trimesh
import numpy as np
from paz.backend.image import load_image
from scipy import spatial
from linemod import LINEMOD
from paz.backend.groups import quaternion_to_rotation_matrix
from pose import EFFICIENTPOSEALINEMODDRILLER


def transform_mesh_points(mesh_points, rotation, translation):
    """Transforms the object points
      # Arguments
          mesh_points: nx3 ndarray with 3D model points.
          rotaion: Rotation matrix
          translation: Translation vector

      # Returns
          Transformed model
      """
    assert (mesh_points.shape[1] == 3)
    pts_t = rotation.dot(mesh_points.T) + translation.reshape((3, 1))
    return pts_t.T


def compute_ADD(true_pose, pred_pose, mesh_points):
    """Calculate The ADD error.
      # Arguments
          true_pose: Real pose
          pred_pose: Predicted pose
          mesh_pts: nx3 ndarray with 3D model points.
      # Returns
          Return ADD error
    """
    quaternion = pred_pose.quaternion
    pred_translation = pred_pose.translation
    pred_rotation = quaternion_to_rotation_matrix(quaternion)
    pred_mesh = transform_mesh_points(mesh_points, pred_rotation,
                                      pred_translation)

    true_rotation = true_pose[:3, :3]
    true_translation = true_pose[:3, 3]
    true_mesh = transform_mesh_points(mesh_points, true_rotation,
                                      true_translation)

    error = np.linalg.norm(pred_mesh - true_mesh, axis=1).mean()
    return error


def compute_ADI(true_pose, pred_pose, mesh_points):
    """Calculate The ADI error.
       Calculate distances to the nearest neighbors from vertices in the
       ground-truth pose to vertices in the estimated pose.
      # Arguments
          true_pose: Real pose
          pred_pose: Predicted pose
          mesh_pts: nx3 ndarray with 3D model points.
      # Returns
          Return ADI error
      """

    quaternion = pred_pose.quaternion
    pred_translation = pred_pose.translation
    pred_rotation = quaternion_to_rotation_matrix(quaternion)

    pred_mesh = transform_mesh_points(mesh_points, pred_rotation,
                                      pred_translation)

    true_rotation = true_pose[:3, :3]
    true_translation = true_pose[:3, 3]
    true_mesh = transform_mesh_points(mesh_points, true_rotation,
                                      true_translation)
    nn_index = spatial.cKDTree(pred_mesh)
    nn_dists, _ = nn_index.query(true_mesh, k=1)

    error = nn_dists.mean()
    return error


class EvaluatePoseError:
    """Callback for evaluating the pose error on ADD and ADI metric.

    # Arguments
        experiment_path: String. Path in which the images will be saved.
        images: List of numpy arrays of shape.
        pipeline: Function that takes as input an element of ''images''
            and outputs a ''Dict'' with inferences.
        mesh_points: nx3 ndarray with 3D model points.
        topic: Key to the ''inferences'' dictionary containing as value the
            drawn inferences.
        verbose: Integer. If is bigger than 1 messages would be displayed.
    """
    def __init__(self, experiment_path, evaluation_data_manager, pipeline,
                 mesh_points, topic='poses6D', verbose=1):
        self.experiment_path = experiment_path
        self.evaluation_data_manager = evaluation_data_manager
        self.images = self._load_test_images()
        self.gt_poses = self._load_gt_poses()
        self.pipeline = pipeline
        self.mesh_points = mesh_points
        self.topic = topic
        self.verbose = verbose

    def _load_test_images(self):
        evaluation_data = self.evaluation_data_manager.load_data()
        evaluation_images = []
        for evaluation_datum in evaluation_data:
            evaluation_image = load_image(evaluation_datum['image'])
            evaluation_images.append(evaluation_image)
        return evaluation_images

    def _load_gt_poses(self):
        evaluation_data = self.evaluation_data_manager.load_data()
        gt_poses = []
        for evaluation_datum in evaluation_data:
            rotation = evaluation_datum['rotation']
            rotation_matrix = rotation.reshape((3, 3))
            translation = evaluation_datum['translation_raw']
            gt_pose = np.concatenate((rotation_matrix, translation.T), axis=1)
            gt_poses.append(gt_pose)
        return gt_poses

    def on_epoch_end(self, epoch, logs=None):
        sum_ADD = 0.0
        sum_ADI = 0.0
        valid_predictions = 0
        for image, gt_pose in zip(self.images, self.gt_poses):
            inferences = self.pipeline(image.copy())
            pose6D = inferences[self.topic]
            if pose6D:
                add_error = compute_ADD(gt_pose, pose6D[0], self.mesh_points)
                adi_error = compute_ADI(gt_pose, pose6D[0], self.mesh_points)
                sum_ADD = sum_ADD + add_error
                sum_ADI = sum_ADI + adi_error
                valid_predictions = valid_predictions + 1

        error_path = os.path.join(self.experiment_path, 'error.txt')
        if valid_predictions > 0:
            average_ADD = sum_ADD / valid_predictions
            average_ADI = sum_ADI / valid_predictions
            with open(error_path, 'a') as filer:
                filer.write('epoch: %d\n' % epoch)
                filer.write('Estimated ADD error: %f\n' % average_ADD)
                filer.write('Estimated ADI error: %f\n\n' % average_ADI)
        else:
            average_ADD = None
            average_ADI = None
        if self.verbose:
            print('Estimated ADD error:', average_ADD)
            print('Estimated ADI error:', average_ADI)


if __name__ == '__main__':
    save_path = 'trained_models/'
    data_path = 'Linemod_preprocessed/'
    object_id = '08'
    data_split = 'test'
    data_name = 'LINEMOD'
    data_managers, datasets, evaluation_data_managers = [], [], []
    eval_data_manager = LINEMOD(
        data_path, object_id, data_split,
        name=data_name, evaluate=True)
    evaluation_data_managers.append(eval_data_manager)

    inference = EFFICIENTPOSEALINEMODDRILLER(score_thresh=0.60,
                                             nms_thresh=0.45)
    inference.model.load_weights('weights.6394-0.25.hdf5')

    mesh_path = data_path + 'models/' + 'obj_' + object_id + '.ply'
    mesh = trimesh.load(mesh_path)
    mesh_points = mesh.vertices.copy()
    pose_error = EvaluatePoseError(save_path, eval_data_manager,
                                   inference, mesh_points)
    pose_error.on_epoch_end(1)
