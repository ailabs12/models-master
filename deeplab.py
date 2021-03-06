import sys
print(sys.version)

#@title Imports

import os
from io import BytesIO
import tarfile
import tempfile
from six.moves import urllib

from matplotlib import gridspec
from matplotlib import pyplot as plt
import numpy as np
from PIL import Image

import tensorflow as tf

import json

import cv2, errno, base64
import sql

#@title Helper methods


class DeepLabModel(object):
  """Class to load deeplab model and run inference."""

  INPUT_TENSOR_NAME = 'ImageTensor:0'
  OUTPUT_TENSOR_NAME = 'SemanticPredictions:0'
  INPUT_SIZE = 513
  FROZEN_GRAPH_NAME = 'frozen_inference_graph'

  def __init__(self, tarball_path):
    """Creates and loads pretrained deeplab model."""
    self.graph = tf.Graph()

    graph_def = None
    # Extract frozen graph from tar archive.
    tar_file = tarfile.open(tarball_path)
    for tar_info in tar_file.getmembers():
      if self.FROZEN_GRAPH_NAME in os.path.basename(tar_info.name):
        file_handle = tar_file.extractfile(tar_info)
        graph_def = tf.GraphDef.FromString(file_handle.read())
        break

    tar_file.close()

    if graph_def is None:
      raise RuntimeError('Cannot find inference graph in tar archive.')

    with self.graph.as_default():
      tf.import_graph_def(graph_def, name='')

    self.sess = tf.Session(graph=self.graph)

  def run(self, image):
    """Runs inference on a single image.

    Args:
      image: A PIL.Image object, raw input image.

    Returns:
      resized_image: RGB image resized from original input image.
      seg_map: Segmentation map of `resized_image`.
    """
    width, height = image.size
    resize_ratio = 1.0 * self.INPUT_SIZE / max(width, height)
    target_size = (int(resize_ratio * width), int(resize_ratio * height))
    resized_image = image.convert('RGB').resize(target_size, Image.ANTIALIAS)
    batch_seg_map = self.sess.run(
        self.OUTPUT_TENSOR_NAME,
        feed_dict={self.INPUT_TENSOR_NAME: [np.asarray(resized_image)]})
    seg_map = batch_seg_map[0]
    return resized_image, seg_map


def create_pascal_label_colormap():
  """Creates a label colormap used in PASCAL VOC segmentation benchmark.

  Returns:
    A Colormap for visualizing segmentation results.
  """
  colormap = np.zeros((256, 3), dtype=int)
  ind = np.arange(256, dtype=int)

  for shift in reversed(range(8)):
    for channel in range(3):
      colormap[:, channel] |= ((ind >> channel) & 1) << shift
    ind >>= 3

  return colormap


def label_to_color_image(label):
  """Adds color defined by the dataset colormap to the label.

  Args:
    label: A 2D array with integer type, storing the segmentation label.

  Returns:
    result: A 2D array with floating type. The element of the array
      is the color indexed by the corresponding element in the input label
      to the PASCAL color map.

  Raises:
    ValueError: If label is not of rank 2 or its value is larger than color
      map maximum entry.
  """
  if label.ndim != 2:
    raise ValueError('Expect 2-D input label')

  colormap = create_pascal_label_colormap()

  if np.max(label) >= len(colormap):
    raise ValueError('label value too large.')

  return colormap[label]


def vis_segmentation(image, seg_map):
  """Visualizes input image, segmentation map and overlay view."""
  plt.figure(figsize=(15, 5))
  grid_spec = gridspec.GridSpec(1, 4, width_ratios=[6, 6, 6, 1])

  plt.subplot(grid_spec[0])
  plt.imshow(image)
  plt.axis('off')
  plt.title('input image')

  plt.subplot(grid_spec[1])
  seg_image = label_to_color_image(seg_map).astype(np.uint8)
  # seg_image.save('seg_image.png');
  plt.imshow(seg_image)
  plt.axis('off')
  plt.title('segmentation map')

  plt.subplot(grid_spec[2])
  plt.imshow(image)
  plt.imshow(seg_image, alpha=0.7)
  plt.axis('off')
  plt.title('segmentation overlay')

  unique_labels = np.unique(seg_map)
  ax = plt.subplot(grid_spec[3])
  plt.imshow(
      FULL_COLOR_MAP[unique_labels].astype(np.uint8), interpolation='nearest')
  ax.yaxis.tick_right()
  plt.yticks(range(len(unique_labels)), LABEL_NAMES[unique_labels])
  plt.xticks([], [])
  ax.tick_params(width=0.0)
  plt.grid('off')
  plt.show()


LABEL_NAMES = np.asarray([
    'background', 'aeroplane', 'bicycle', 'bird', 'boat', 'bottle', 'bus',
    'car', 'cat', 'chair', 'cow', 'diningtable', 'dog', 'horse', 'motorbike',
    'person', 'pottedplant', 'sheep', 'sofa', 'train', 'tv'
])

FULL_LABEL_MAP = np.arange(len(LABEL_NAMES)).reshape(len(LABEL_NAMES), 1)
FULL_COLOR_MAP = label_to_color_image(FULL_LABEL_MAP)




#@title Select and download models {display-mode: "form"}

MODEL_NAME = 'mobilenetv2_coco_voctrainaug'  # @param ['mobilenetv2_coco_voctrainaug', 'mobilenetv2_coco_voctrainval', 'xception_coco_voctrainaug', 'xception_coco_voctrainval']

_DOWNLOAD_URL_PREFIX = 'http://download.tensorflow.org/models/'
_MODEL_URLS = {
    'mobilenetv2_coco_voctrainaug':
        'deeplabv3_mnv2_pascal_train_aug_2018_01_29.tar.gz',
    'mobilenetv2_coco_voctrainval':
        'deeplabv3_mnv2_pascal_trainval_2018_01_29.tar.gz',
    'xception_coco_voctrainaug':
        'deeplabv3_pascal_train_aug_2018_01_04.tar.gz',
    'xception_coco_voctrainval':
        'deeplabv3_pascal_trainval_2018_01_04.tar.gz',
}
_TARBALL_NAME = 'deeplab_model.tar.gz'

model_dir = tempfile.mkdtemp()
tf.gfile.MakeDirs(model_dir)

download_path = os.path.join(model_dir, _TARBALL_NAME)
print('downloading model, this might take a while...')
urllib.request.urlretrieve(_DOWNLOAD_URL_PREFIX + _MODEL_URLS[MODEL_NAME],
                   download_path)
print('download completed! loading DeepLab model...')

MODEL = DeepLabModel(download_path)
print('model loaded successfully!')

counter_image = 1

def run_visualization(url):
  """Inferences DeepLab model and visualizes result."""

  global counter_image
  db = 'test.db'

  images_path = './images'
  frames_path = images_path + '/frames/'
  object_path = images_path + '/objects/'

  try:
    os.makedirs(images_path)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise

  try:
    os.makedirs(frames_path)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise

  try:
    f = urllib.request.urlopen(url)
    jpeg_str = f.read()

    original_im = Image.open(BytesIO(jpeg_str))
    original_im.save(frames_path + str(counter_image) + '.jpeg')

    outputBuffer = BytesIO()
    original_im.save(outputBuffer, format='JPEG')
    imageBase64Data = outputBuffer.getvalue()
    data = base64.b64encode(imageBase64Data)
    outputBuffer.close()
    sql.add_record(db, data)

  except IOError:
    print('Cannot retrieve image. Please check url: ' + url)
    return

  # print('running deeplab on image %s...' % url)
  resized_im, seg_map = MODEL.run(original_im)
  resized_im = resized_im.convert('RGBA')

  detected_objects = { "image": "data:image/jpeg;base64," + data }

  list3d = [[[(0, 0, 0, 0) for j in range( len(seg_map[i]) )] for i in range( len(seg_map) )] for k in range( len(LABEL_NAMES) )]
  # print( len(seg_map) )

  # Formation of the list of found classes
  for i in range( len(seg_map) ):
    for j in range( len(seg_map[i]) ):
      if not( LABEL_NAMES[ seg_map[i][j] ] in detected_objects):
        detected_objects[ LABEL_NAMES[seg_map[i][j] ] ] = []
      tuple_color = resized_im.getpixel( (j,i) )
      # detected_objects[ LABEL_NAMES[ seg_map[i][j] ] ].append( { 'y': i, 'x': j, 'rgba': tuple_color } )
      detected_objects[ LABEL_NAMES[ seg_map[i][j] ] ].append([j,i])
      list3d[seg_map[i][j]][i][j] = tuple_color

  # Classes output
  for k in range( len(LABEL_NAMES) ):
    if LABEL_NAMES[k] in detected_objects.keys():
      pix = np.array(list3d[k]) #, dtype=object
      pix = pix.astype(np.float32)
      pix = cv2.cvtColor(pix, cv2.COLOR_BGR2RGBA)
      data = cv2.imencode('.jpeg', pix)[1].tostring()
      sql.add_record_class(db, LABEL_NAMES[k])
      sql.add_record_child(db, LABEL_NAMES[k], data)

      if not os.path.exists(object_path + LABEL_NAMES[k]):
        try:
          os.makedirs(object_path + LABEL_NAMES[k])
          cv2.imwrite(object_path + LABEL_NAMES[k] + '/frame_' + str(counter_image) + '_' + LABEL_NAMES[k] + '.jpeg', pix)
        except OSError as e:
          if e.errno != errno.EEXIST:
            raise
      else:
        cv2.imwrite(object_path + LABEL_NAMES[k] + '/frame_' + str(counter_image) + '_' + LABEL_NAMES[k] + '.jpeg', pix)

  counter_image+=1
  
  # print( "Value : %s" %  detected_objects.keys() )
  # res_orig = sql.extr_record(db, 1)
  # res_child = sql.child_extr_record(db, 1)
  #print "Value : %s" %  detected_objects.keys() ##########

  image_array = open('image_array.txt', 'w')
  image_array.write(json.dumps(detected_objects, sort_keys=True))
  image_array.close()

  # resized_im.putpixel((25, 45), (255, 0, 0))
  # original_im[]

  # import scipy.misc
  # scipy.misc.imsave('image_test.png', seg_map)

  #vis_segmentation(resized_im, seg_map) ###########
  # return detected_objects.keys()
  return detected_objects



############# Example run segmentations #############
# SAMPLE_IMAGE = 'image1'  # @param ['image1', 'image2', 'image3']

# IMAGE_URL = 'https://static.mk.ru/upload/entities/2018/07/27/articles/detailPicture/29/bc/22/88/836556deb3f8e01b2d80a627916145f1.jpg'
# found_objects = run_visualization(IMAGE_URL)
# print(found_objects)

############# Example of working with database #############
# res_orig2 = sql.extr_record('test.db', 1)
# print(res_orig2)

# res_child2 = sql.child_extr_record('test.db', 1)
# print(res_child2)