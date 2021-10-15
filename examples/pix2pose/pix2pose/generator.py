from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, Conv2D, Activation, Dense, Reshape, Conv2DTranspose, Flatten,
    LeakyReLU, BatchNormalization, Concatenate)


def encoder_convolution_block(x, filters, strides=(2, 2)):
    x = Conv2D(filters, (5, 5), strides=strides, padding='same')(x)
    x = BatchNormalization()(x)
    x = LeakyReLU()(x)
    return x


def encoder_block(x, filters):
    x_stem = encoder_convolution_block(x, filters)
    x_skip = encoder_convolution_block(x, filters)
    x_stem = Concatenate()([x_stem, x_skip])
    return x_stem, x_skip


def encoder(x):
    x, skip_1 = encoder_block(x, 64)
    x, skip_2 = encoder_block(x, 128)
    x, skip_3 = encoder_block(x, 128)
    x, skip_4 = encoder_block(x, 256)
    return x, [skip_1, skip_2, skip_3]


def decoder_convolution_block(x, filters, strides=(2, 2)):
    x = Conv2DTranspose(filters, (5, 5), strides=strides, padding='same')(x)
    x = BatchNormalization()(x)
    x = LeakyReLU()(x)
    return x


def decoder_block(x, x_skip, filters):
    filters_1, filters_2 = filters
    x = decoder_convolution_block(x, filters_1, (1, 1))
    x = decoder_convolution_block(x, filters_2)
    x = Concatenate()([x, x_skip])
    return x


def decoder(x, skip_connections):
    skip_1, skip_2, skip_3 = skip_connections
    x = decoder_convolution_block(x, 256)
    x = Concatenate()([x, skip_3])
    x = decoder_block(x, skip_2, [256, 128])
    x = decoder_block(x, skip_1, [256, 64])
    x = decoder_convolution_block(x, 128, (1, 1))
    return x


def Generator(input_shape=(128, 128, 3), latent_dimension=256,
              name='PIX2POSE_GENERATOR'):
    input_image = Input(input_shape, name='input_image')
    x, skip_connections = encoder(input_image)
    x = Flatten()(x)
    x = Dense(latent_dimension)(x)
    x = Dense(8 * 8 * latent_dimension)(x)
    x = Reshape((8, 8, latent_dimension))(x)
    x = decoder(x, skip_connections)
    RGB_mask = Conv2DTranspose(3, (5, 5), strides=(2, 2), padding='same')(x)
    RGB_mask = Activation('tanh', name='RGB_mask')(RGB_mask)
    error_mask = Conv2DTranspose(1, (5, 5), (2, 2), padding='same')(x)
    error_mask = Activation('sigmoid', name='error_mask')(error_mask)
    model = Model([input_image], [RGB_mask, error_mask], name=name)
    return model


model = Generator()
assert model.count_params() == 25740356
assert model.output_shape == [(None, 128, 128, 3), (None, 128, 128, 1)]
assert model.input_shape == (None, 128, 128, 3)
