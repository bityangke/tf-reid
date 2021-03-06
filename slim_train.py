import tensorflow as tf
from market1501_input import *
from nets import nets_factory
from preprocessing import *
import os
import feature_util


slim = tf.contrib.slim
tf.logging.set_verbosity(tf.logging.INFO)

tf.app.flags.DEFINE_string(
    'train_dir', '/tmp/checkpoints/market-1501',
    'Directory where checkpoints and event logs are written to.')


tf.app.flags.DEFINE_string(
    'dataset_name', 'market-1501_', 'The name of the dataset to load.')

tf.app.flags.DEFINE_string(
    'dataset_split_name', 'train', 'The name of the train/test split.')

tf.app.flags.DEFINE_string(
    'dataset_dir', '/tmp/Market-1501/', 'The directory where the dataset files are stored.')


tf.app.flags.DEFINE_integer(
    'num_readers', 4,
    'The number of parallel readers that read data from the dataset.')


tf.app.flags.DEFINE_integer(
    'labels_offset', 0,
    'An offset for the labels in the dataset. This flag is primarily used to '
    'evaluate the VGG and ResNet architectures which do not use a background '
    'class for the ImageNet dataset.')

tf.app.flags.DEFINE_string(
    'model_name', 'inception_v3', 'The name of the architecture to train.')

tf.app.flags.DEFINE_string(
    'preprocessing_name', None, 'The name of the preprocessing to use. If left '
    'as `None`, then the model_name flag is used.')

tf.app.flags.DEFINE_integer(
    'batch_size', 32, 'The number of samples in each batch.')

tf.app.flags.DEFINE_integer(
    'train_image_size', 12936, 'Train image size')

tf.app.flags.DEFINE_integer('max_number_of_steps', None,
                            'The maximum number of training steps.')

tf.app.flags.DEFINE_integer(
    'log_every_n_steps', 10,
    'The frequency with which logs are print.')

tf.app.flags.DEFINE_string(
    'checkpoint_path', '/tmp/checkpoints/inception_v3.ckpt',
    'The path to a checkpoint from which to fine-tune.')

tf.app.flags.DEFINE_string(
    'checkpoint_exclude_scopes', 'InceptionV3/Logits,InceptionV3/AuxLogits',
    'The path to a checkpoint from which to fine-tune.')

tf.app.flags.DEFINE_string(
    'trainable_scopes', None,
    'Comma-separated list of scopes to filter the set of variables to train.'
    'By default, None would train all the variables.')



######################
# Optimization Flags #
######################

tf.app.flags.DEFINE_float(
    'weight_decay', 0.0005, 'The weight decay on the model weights.')


FLAGS = tf.app.flags.FLAGS


def _get_init_fn():


    """Returns a function run by the chief worker to warm-start the training.

    Note that the init_fn is only run when initializing the model during the very
    first global step.

    Returns:
    An init function run by the supervisor.
    """

    if FLAGS.checkpoint_path is None:
        return None

    # Warn the user if a checkpoint exists in the train_dir. Then we'll be
    # ignoring the checkpoint anyway.
    # if tf.train.latest_checkpoint(FLAGS.train_dir):
    #     tf.logging.info(
    #     'Ignoring --checkpoint_path because a checkpoint already exists in %s'
    #     % FLAGS.train_dir)
    #     return None

    exclusions = []
    if FLAGS.checkpoint_exclude_scopes:
        exclusions = [scope.strip()
            for scope in FLAGS.checkpoint_exclude_scopes.split(',')]

    variables_to_restore = []
    for var in slim.get_model_variables():
        excluded = False
        for exclusion in exclusions:
            if var.op.name.startswith(exclusion):
                excluded = True
                break
        if not excluded:
            variables_to_restore.append(var)

    if tf.gfile.IsDirectory(FLAGS.checkpoint_path):
        checkpoint_path = tf.train.latest_checkpoint(FLAGS.checkpoint_path)
    else:
        checkpoint_path = FLAGS.checkpoint_path

    tf.logging.info('Fine-tuning from %s' % checkpoint_path)

    return slim.assign_from_checkpoint_fn(
            checkpoint_path,
            variables_to_restore)

def _get_variables_to_train():
  """Returns a list of variables to train.

  Returns:
    A list of variables to train by the optimizer.
  """
  if FLAGS.trainable_scopes is None:
    return tf.trainable_variables()
  else:
    scopes = [scope.strip() for scope in FLAGS.trainable_scopes.split(',')]

  variables_to_train = []
  for scope in scopes:
    variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope)
    variables_to_train.extend(variables)
  return variables_to_train



def get_restore_variabels():
    exclusions = []

    exclusions = [scope.strip()
        for scope in FLAGS.checkpoint_exclude_scopes.split(',')]

    variables_to_restore = []
    for var in slim.get_model_variables():
        excluded = False
        for exclusion in exclusions:
            if var.op.name.startswith(exclusion):
                excluded = True
                break
        if not excluded:
            variables_to_restore.append(var)

    return variables_to_restore


def initialize_uninitialized_vars(sess):
    from itertools import compress
    global_vars = tf.global_variables()
    is_not_initialized = sess.run([~(tf.is_variable_initialized(var)) \
                                   for var in global_vars])
    not_initialized_vars = list(compress(global_vars, is_not_initialized))

    if len(not_initialized_vars):
        sess.run(tf.variables_initializer(not_initialized_vars))




def main(_):




    with tf.Graph().as_default():
        #############
        # data set
        ############
        # images,labels,_ = input_fn(record_file,True)
        dataset=make_slim_dataset(FLAGS.dataset_split_name, FLAGS.dataset_dir)
        provider = slim.dataset_data_provider.DatasetDataProvider(dataset,shuffle=True)
        image,label = provider.get(['image','label'])
        images = preprocess_image(image,224,True)
        labels = tf.contrib.layers.one_hot_encoding(label,751)
        images,labels = tf.train.batch([images,labels],batch_size=32,num_threads=5,capacity=32*5,name='batch')

        ################
        # select network
        ################
        network_fn = nets_factory.get_network_fn(
            FLAGS.model_name,
            num_classes=751,
            weight_decay=FLAGS.weight_decay,
            is_training=True
        )


        network_fn(images)

        feature_name = feature_util.get_last_feature_name(model_name=FLAGS.model_name)
        feature = tf.get_default_graph().get_tensor_by_name(feature_name)
        feature = tf.layers.dropout(feature,rate=0.3,training=True,name='drop_feature')
        logits = tf.layers.conv2d(feature,751,[1,1],activation=None,name='logits')
        logits = tf.squeeze(logits,name='squeeze_class')
        total_loss = tf.losses.softmax_cross_entropy(
                logits=logits, onehot_labels=labels)

        global_step = tf.Variable(0,trainable=False)
        learning_rate = tf.train.polynomial_decay(0.001,global_step,decay_steps=16000)
        optimizer = tf.train.GradientDescentOptimizer(learning_rate)
        #optimizer = tf.train.MomentumOptimizer(learning_rate,0.9)


        variables_to_train = _get_variables_to_train()
        train_op = slim.learning.create_train_op(total_loss, optimizer,variables_to_train=variables_to_train)

        slim.learning.train(
            train_op,
            logdir=FLAGS.train_dir,
            init_fn=_get_init_fn(),
            number_of_steps=FLAGS.max_number_of_steps,
            log_every_n_steps=20,
            save_summaries_secs=600
        )


if __name__ == '__main__':
    tf.app.run()
