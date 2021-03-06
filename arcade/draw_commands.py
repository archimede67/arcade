"""
This module contains commands for basic graphics drawing commands.
(Drawing primitives.)

Many of these commands are slow, because they load everything to the
graphics card each time a shape is drawn. For faster drawing, see the
Buffered Draw Commands.
"""
# pylint: disable=too-many-arguments, too-many-locals, too-few-public-methods

import ctypes
import math
import PIL.Image
import PIL.ImageOps
import numpy as np
import moderngl

import pyglet.gl as gl

from typing import List

from arcade.window_commands import get_projection
from arcade.window_commands import get_window
from arcade.arcade_types import Color
from arcade.arcade_types import PointList
from arcade import shader


line_vertex_shader = '''
    #version 330
    uniform mat4 Projection;
    in vec2 in_vert;
    in vec4 in_color;
    out vec4 v_color;
    void main() {
       gl_Position = Projection * vec4(in_vert, 0.0, 1.0);
       v_color = in_color;
    }
'''

line_fragment_shader = '''
    #version 330
    in vec4 v_color;
    out vec4 f_color;
    void main() {
        f_color = v_color;
    }
'''


def get_four_byte_color(color: Color) -> Color:
    """
    Given a RGB list, it will return RGBA.
    Given a RGBA list, it will return the same RGBA.

    :param color: Color
    :return: color: Color
    """
    if len(color) == 4:
        return color
    elif len(color) == 3:
        return color[0], color[1], color[2], 255
    else:
        raise ValueError("This isn't a 3 or 4 byte color")


def get_four_float_color(color: Color) -> (float, float, float, float):
    """
    Given a 3 or 4 RGB/RGBA color where each color goes 0-255, this
    returns a RGBA list where each item is a scaled float from 0 to 1.

    :param color:
    :return:
    """
    if len(color) == 4:
        return color[0] / 255, color[1] / 255, color[2] / 255, color[3] / 255
    elif len(color) == 3:
        return color[0] / 255, color[1] / 255, color[2] / 255, 1.0
    else:
        raise ValueError("This isn't a 3 or 4 byte color")


def make_transparent_color(color: Color, transparency: float):
    """
    Given a RGB color, along with an alpha, returns a RGBA color tuple.
    """
    return color[0], color[1], color[2], transparency


def rotate_point(x: float, y: float, cx: float, cy: float,
                 angle: float) -> (float, float):
    """
    Rotate a point around a center.

    :param x: x value of the point you want to rotate
    :param y: y value of the point you want to rotate
    :param cx: x value of the center point you want to rotate around
    :param cy: y value of the center point you want to rotate around
    :param angle: Angle, in degrees, to rotate
    :return: Return rotated (x, y) pair

    >>> x, y = rotate_point(1, 1, 0, 0, 90)
    >>> print("x = {:.1f}, y = {:.1f}".format(x, y))
    x = -1.0, y = 1.0
    """
    temp_x = x - cx
    temp_y = y - cy

    # now apply rotation
    rotated_x = temp_x * math.cos(math.radians(angle)) - temp_y * math.sin(math.radians(angle))
    rotated_y = temp_x * math.sin(math.radians(angle)) + temp_y * math.cos(math.radians(angle))

    # translate back
    rounding_precision = 2
    x = round(rotated_x + cx, rounding_precision)
    y = round(rotated_y + cy, rounding_precision)

    return x, y


class Texture:
    """
    Class that represents a texture.
    Usually created by the ``load_texture`` or ``load_textures`` commands.

    Attributes:
        :id: ID of the texture as assigned by OpenGL
        :width: Width of the texture image in pixels
        :height: Height of the texture image in pixels

    """

    def __init__(self, texture_id: int, width: float, height: float, file_name: str):
        """
        Args:
            :texture_id (str): Id of the texture.
            :width (int): Width of the texture.
            :height (int): Height of the texture.
        Raises:
            :ValueError:

        >>> texture_id = Texture(0, 10, -10)
        Traceback (most recent call last):
        ...
        ValueError: Height entered is less than zero. Height must be a positive float.
        >>> texture_id = Texture(0, -10, 10)
        Traceback (most recent call last):
        ...
        ValueError: Width entered is less than zero. Width must be a positive float.
        """
        # Check values before attempting to create Texture object
        if height < 0:
            raise ValueError("Height entered is less than zero. Height must "
                             "be a positive float.")

        if width < 0:
            raise ValueError("Width entered is less than zero. Width must be "
                             "a positive float.")

        # Values seem to be clear, create object
        self.texture_id = texture_id
        self.width = width
        self.height = height
        self.texture_name = file_name
        self._sprite = None
        self._sprite_list = None

    def draw(self, center_x: float, center_y: float, width: float,
             height: float, angle: float=0,
             alpha: float=1, transparent: bool=True,
             repeat_count_x=1, repeat_count_y=1):

        from arcade.sprite import Sprite
        from arcade.sprite_list import SpriteList

        if self._sprite == None:
            self._sprite = Sprite()
            self._sprite.texture = self
            self._sprite.textures = [self]

            self._sprite_list = SpriteList()
            self._sprite_list.append(self._sprite)

        self._sprite.center_x = center_x
        self._sprite.center_y = center_y
        self._sprite.width = width
        self._sprite.height = height
        self._sprite.angle = angle

        self._sprite_list.draw()

def load_textures(file_name: str,
                  image_location_list: PointList,
                  mirrored: bool=False,
                  flipped: bool=False,
                  scale: float=1) -> List['Texture']:
    """
    Load a set of textures off of a single image file.

    Note, if the code is to load only part of the image, the given x, y
    coordinates will start with the origin (0, 0) in the upper left of the
    image. When drawing, Arcade uses (0, 0)
    in the lower left corner when drawing. Be careful about this reversal.

    For a longer explanation of why computers sometimes start in the upper
    left, see:
    http://programarcadegames.com/index.php?chapter=introduction_to_graphics&lang=en#section_5

    Args:
        :file_name: Name of the file.
        :image_location_list: List of image locations. Each location should be
         a list of four floats. ``[x, y, width, height]``.
        :mirrored=False: If set to true, the image is mirrored left to right.
        :flipped=False: If set to true, the image is flipped upside down.
    Returns:
        :list: List of textures loaded.
    Raises:
        :SystemError:
    """
    source_image = PIL.Image.open(file_name)

    source_image_width, source_image_height = source_image.size
    texture_info_list = []
    for image_location in image_location_list:
        x, y, width, height = image_location

        if width <= 0:
            raise ValueError("Texture has a width of {}, must be > 0."
                             .format(width))
        if x > source_image_width:
            raise ValueError("Can't load texture starting at an x of {} "
                             "when the image is only {} across."
                             .format(x, source_image_width))
        if y > source_image_height:
            raise ValueError("Can't load texture starting at an y of {} "
                             "when the image is only {} high."
                             .format(y, source_image_height))
        if x + width > source_image_width:
            raise ValueError("Can't load texture ending at an x of {} "
                             "when the image is only {} wide."
                             .format(x + width, source_image_width))
        if y + height > source_image_height:
            raise ValueError("Can't load texture ending at an y of {} "
                             "when the image is only {} high."
                             .format(y + height, source_image_height))

        image = source_image.crop((x, y, x + width, y + height))
        # image = _trim_image(image)

        if mirrored:
            image = PIL.ImageOps.mirror(image)

        if flipped:
            image = PIL.ImageOps.flip(image)

        image_width, image_height = image.size

        texture = gl.GLuint(0)
        gl.glGenTextures(1, ctypes.byref(texture))

        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)

        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_LINEAR_MIPMAP_LINEAR)

        image_width *= scale
        image_height *= scale

        texture_info_list.append(Texture(texture, width, height, image_location))

    return texture_info_list


def load_texture(file_name: str, x: float=0, y: float=0,
                 width: float=0, height: float=0,
                 mirrored: bool=False,
                 flipped: bool=False,
                 scale: float=1) -> Texture:
    """
    Load image from disk and create a texture.

    Note, if the code is to load only part of the image, the given x, y
    coordinates will start with the origin (0, 0) in the upper left of the
    image. When drawing, Arcade uses (0, 0)
    in the lower left corner when drawing. Be careful about this reversal.

    For a longer explanation of why computers sometimes start in the upper
    left, see:
    http://programarcadegames.com/index.php?chapter=introduction_to_graphics&lang=en#section_5

    Args:
        :filename (str): Name of the file to that holds the texture.
        :x (float): X position of the crop area of the texture.
        :y (float): Y position of the crop area of the texture.
        :width (float): Width of the crop area of the texture.
        :height (float): Height of the crop area of the texture.
        :scale (float): Scale factor to apply on the new texture.
    Returns:
        The new texture.
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> name = "arcade/examples/images/meteorGrey_big1.png"
    >>> texture1 = load_texture(name, 1, 1, 50, 50)
    >>> texture2 = load_texture(name, 1, 1, 50, 50)

    >>> texture = load_texture(name, 200, 1, 50, 50)
    Traceback (most recent call last):
    ...
    ValueError: Can't load texture starting at an x of 200 when the image is only 101 across.

    >>> texture = load_texture(name, 1, 50, 50, 50)
    Traceback (most recent call last):
    ...
    ValueError: Can't load texture ending at an y of 100 when the image is only 84 high.

    >>> texture = load_texture(name, 1, 150, 50, 50)
    Traceback (most recent call last):
    ...
    ValueError: Can't load texture starting at an y of 150 when the image is only 84 high.

    >>> texture = load_texture(name, 0, 0, 400, 50)
    Traceback (most recent call last):
    ...
    ValueError: Can't load texture ending at an x of 400 when the image is only 101 wide.

    >>> arcade.close_window()
    """

    # See if we already loaded this file, and we can just use a cached version.
    cache_name = "{}{}{}{}{}{}{}{}".format(file_name, x, y, width, height, scale, flipped, mirrored)
    if cache_name in load_texture.texture_cache:
        return load_texture.texture_cache[cache_name]

    source_image = PIL.Image.open(file_name)

    source_image_width, source_image_height = source_image.size

    if x != 0 or y != 0 or width != 0 or height != 0:
        if x > source_image_width:
            raise ValueError("Can't load texture starting at an x of {} "
                             "when the image is only {} across."
                             .format(x, source_image_width))
        if y > source_image_height:
            raise ValueError("Can't load texture starting at an y of {} "
                             "when the image is only {} high."
                             .format(y, source_image_height))
        if x + width > source_image_width:
            raise ValueError("Can't load texture ending at an x of {} "
                             "when the image is only {} wide."
                             .format(x + width, source_image_width))
        if y + height > source_image_height:
            raise ValueError("Can't load texture ending at an y of {} "
                             "when the image is only {} high."
                             .format(y + height, source_image_height))

        image = source_image.crop((x, y, x + width, y + height))
    else:
        image = source_image

    # image = _trim_image(image)
    if mirrored:
        image = PIL.ImageOps.mirror(image)

    if flipped:
        image = PIL.ImageOps.flip(image)

    image_width, image_height = image.size
    # image_bytes = image.convert("RGBA").tobytes("raw", "RGBA", 0, -1)

    texture = gl.GLuint(0)
    gl.glGenTextures(1, ctypes.byref(texture))

    gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

    gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S,
                       gl.GL_REPEAT)
    gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T,
                       gl.GL_REPEAT)

    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                       gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                       gl.GL_LINEAR_MIPMAP_LINEAR)
    # glu.gluBuild2DMipmaps(gl.GL_TEXTURE_2D, gl.GL_RGBA,
    #                       image_width, image_height,
    #                       gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, image_bytes)

    image_width *= scale
    image_height *= scale

    result = Texture(texture, image_width, image_height, file_name)
    load_texture.texture_cache[cache_name] = result
    return result


load_texture.texture_cache = dict()


# --- END TEXTURE FUNCTIONS # # #


def trim_image(image: PIL.Image) -> PIL.Image:
    """
    Returns an image with extra whitespace cropped out.

    >>> name = "arcade/examples/images/playerShip1_orange.png"
    >>> source_image = PIL.Image.open(name)
    >>> cropped_image = trim_image(source_image)
    >>> print(source_image.height, cropped_image.height)
    75 75
    """
    bbox = image.getbbox()
    return image.crop(bbox)


# --- BEGIN ARC FUNCTIONS # # #


def draw_arc_filled(center_x: float, center_y: float,
                    width: float, height: float,
                    color: Color,
                    start_angle: float, end_angle: float,
                    tilt_angle: float=0,
                    num_segments: int=128):
    """
    Draw a filled in arc. Useful for drawing pie-wedges, or Pac-Man.

    Args:
        :center_x: x position that is the center of the arc.
        :center_y: y position that is the center of the arc.
        :width: width of the arc.
        :height: height of the arc.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :start_angle: start angle of the arc in degrees.
        :end_angle: end angle of the arc in degrees.
        :tilt_angle: angle the arc is tilted.
    Returns:
        None
    Raises:
        None
    """
    unrotated_point_list = [[0, 0]]

    start_segment = int(start_angle / 360 * num_segments)
    end_segment = int(end_angle / 360 * num_segments)

    for segment in range(start_segment, end_segment + 1):
        theta = 2.0 * 3.1415926 * segment / num_segments

        x = width * math.cos(theta)
        y = height * math.sin(theta)

        unrotated_point_list.append((x, y))

    if tilt_angle == 0:
        uncentered_point_list = unrotated_point_list
    else:
        uncentered_point_list = []
        for point in unrotated_point_list:
            uncentered_point_list.append(rotate_point(point[0], point[1], 0, 0, tilt_angle))

    point_list = []
    for point in uncentered_point_list:
        point_list.append((point[0] + center_x, point[1] + center_y))

    _generic_draw_line_strip(point_list, color, 1, gl.GL_TRIANGLE_FAN)


def draw_arc_outline(center_x: float, center_y: float, width: float,
                     height: float, color: Color,
                     start_angle: float, end_angle: float,
                     border_width: float=1, tilt_angle: float=0,
                     num_segments: int=128):
    """
    Draw the outside edge of an arc. Useful for drawing curved lines.

    Args:
        :center_x: x position that is the center of the arc.
        :center_y: y position that is the center of the arc.
        :width: width of the arc.
        :height: height of the arc.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :start_angle: start angle of the arc in degrees.
        :end_angle: end angle of the arc in degrees.
        :border_width: width of line in pixels.
        :angle: angle the arc is tilted.
    Returns:
        None
    Raises:
        None
    """
    unrotated_point_list = []

    start_segment = int(start_angle / 360 * num_segments)
    end_segment = int(end_angle / 360 * num_segments)

    inside_width = width - border_width / 2
    outside_width = width + border_width / 2
    inside_height = height - border_width / 2
    outside_height = height + border_width / 2

    for segment in range(start_segment, end_segment + 1):
        theta = 2.0 * math.pi * segment / num_segments

        x1 = inside_width * math.cos(theta)
        y1 = inside_height * math.sin(theta)

        x2 = outside_width * math.cos(theta)
        y2 = outside_height * math.sin(theta)

        unrotated_point_list.append((x1, y1))
        unrotated_point_list.append((x2, y2))

    if tilt_angle == 0:
        uncentered_point_list = unrotated_point_list
    else:
        uncentered_point_list = []
        for point in unrotated_point_list:
            uncentered_point_list.append(rotate_point(point[0], point[1], 0, 0, tilt_angle))

    point_list = []
    for point in uncentered_point_list:
        point_list.append((point[0] + center_x, point[1] + center_y))

    _generic_draw_line_strip(point_list, color, 1, gl.GL_TRIANGLE_STRIP)


# --- END ARC FUNCTIONS # # #


# --- BEGIN PARABOLA FUNCTIONS # # #

def draw_parabola_filled(start_x: float, start_y: float, end_x: float,
                         height: float, color: Color,
                         tilt_angle: float=0):
    """
    Draws a filled in parabola.

    Args:
        :start_x: The starting x position of the parabola
        :start_y: The starting y position of the parabola
        :end_x: The ending x position of the parabola
        :height: The height of the parabola
        :color: The color of the parabola
        :tilt_angle: The angle of the tilt of the parabola
    Returns:
        None
    Raises:
        None

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_parabola_filled(150, 150, 200, 50, \
arcade.color.BOTTLE_GREEN)
    >>> color = (255, 0, 0, 127)
    >>> arcade.draw_parabola_filled(160, 160, 210, 50, color)
    >>> arcade.finish_render()
    >>> arcade.close_window()
    """
    center_x = (start_x + end_x) / 2
    center_y = start_y + height
    start_angle = 0
    end_angle = 180
    width = (start_x - end_x)
    draw_arc_filled(center_x, center_y, width, height, color,
                    start_angle, end_angle, tilt_angle)


def draw_parabola_outline(start_x: float, start_y: float, end_x: float,
                          height: float, color: Color,
                          border_width: float=1, tilt_angle: float=0):
    """
    Draws the outline of a parabola.

    Args:
        :start_x: The starting x position of the parabola
        :start_y: The starting y position of the parabola
        :end_x: The ending x position of the parabola
        :height: The height of the parabola
        :color: The color of the parabola
        :border_width: The width of the parabola
        :tile_angle: The angle of the tilt of the parabola
    Returns:
        None
    Raises:
        None

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_parabola_outline(150, 150, 200, 50, \
arcade.color.BOTTLE_GREEN, 10, 15)
    >>> color = (255, 0, 0, 127)
    >>> arcade.draw_parabola_outline(160, 160, 210, 50, color, 20)
    >>> arcade.finish_render()
    >>> arcade.close_window()
    """
    center_x = (start_x + end_x) / 2
    center_y = start_y + height
    start_angle = 0
    end_angle = 180
    width = (start_x - end_x)
    draw_arc_outline(center_x, center_y, width, height, color,
                     start_angle, end_angle, border_width, tilt_angle)


# --- END PARABOLA FUNCTIONS # # #


# --- BEGIN CIRCLE FUNCTIONS # # #

def draw_circle_filled(center_x: float, center_y: float, radius: float,
                       color: Color):
    """
    Draw a filled-in circle.

    Args:
        :center_x: x position that is the center of the circle.
        :center_y: y position that is the center of the circle.
        :radius: width of the circle.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :num_segments (int): float of triangle segments that make up this
         circle. Higher is better quality, but slower render time.
    Returns:
        None
    Raises:
        None

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_circle_filled(420, 285, 18, arcade.color.GREEN)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """
    width = radius
    height = radius
    draw_ellipse_filled(center_x, center_y, width, height, color)


def draw_circle_outline(center_x: float, center_y: float, radius: float,
                        color: Color, border_width: float=1):
    """
    Draw the outline of a circle.

    Args:
        :center_x: x position that is the center of the circle.
        :center_y: y position that is the center of the circle.
        :radius: width of the circle.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the circle outline in pixels.
        :num_segments: float of triangle segments that make up this
         circle. Higher is better quality, but slower render time.
    Returns:
        None
    Raises:
        None

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_circle_outline(300, 285, 18, arcade.color.WISTERIA, 3)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """
    width = radius
    height = radius
    draw_ellipse_outline(center_x, center_y, width, height,
                         color, border_width)


# --- END CIRCLE FUNCTIONS # # #


# --- BEGIN ELLIPSE FUNCTIONS # # #

def draw_ellipse_filled(center_x: float, center_y: float,
                        width: float, height: float, color: Color,
                        tilt_angle: float=0, num_segments=128):
    """
    Draw a filled in ellipse.

    Args:
        :center_x: x position that is the center of the circle.
        :center_y: y position that is the center of the circle.
        :height: height of the ellipse.
        :width: width of the ellipse.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :angle: Angle in degrees to tilt the ellipse.
        :num_segments: float of triangle segments that make up this
         circle. Higher is better quality, but slower render time.
    Returns:
        None
    Raises:
        None

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_ellipse_filled(60, 81, 15, 36, arcade.color.AMBER)
    >>> color = (127, 0, 127, 127)
    >>> arcade.draw_ellipse_filled(60, 144, 15, 36, color, 45)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    unrotated_point_list = []

    for segment in range(num_segments):
        theta = 2.0 * 3.1415926 * segment / num_segments

        x = width * math.cos(theta)
        y = height * math.sin(theta)

        unrotated_point_list.append((x, y))

    if tilt_angle == 0:
        uncentered_point_list = unrotated_point_list
    else:
        uncentered_point_list = []
        for point in unrotated_point_list:
            uncentered_point_list.append(rotate_point(point[0], point[1], 0, 0, tilt_angle))

    point_list = []
    for point in uncentered_point_list:
        point_list.append((point[0] + center_x, point[1] + center_y))

    _generic_draw_line_strip(point_list, color, 1, gl.GL_TRIANGLE_FAN)


def draw_ellipse_outline(center_x: float, center_y: float, width: float,
                         height: float, color: Color,
                         border_width: float=1, tilt_angle: float=0,
                         num_segments=128):
    """
    Draw the outline of an ellipse.

    Args:
        :center_x: x position that is the center of the circle.
        :center_y: y position that is the center of the circle.
        :height: height of the ellipse.
        :width: width of the ellipse.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the circle outline in pixels.
        :tilt_angle: Angle in degrees to tilt the ellipse.
    Returns:
        None
    Raises:
        None
    """

    unrotated_point_list = []

    for segment in range(num_segments):
        theta = 2.0 * 3.1415926 * segment / num_segments

        x = width * math.cos(theta)
        y = height * math.sin(theta)

        unrotated_point_list.append((x, y))

    if tilt_angle == 0:
        uncentered_point_list = unrotated_point_list
    else:
        uncentered_point_list = []
        for point in unrotated_point_list:
            uncentered_point_list.append(rotate_point(point[0], point[1], 0, 0, tilt_angle))

    point_list = []
    for point in uncentered_point_list:
        point_list.append((point[0] + center_x, point[1] + center_y))

    _generic_draw_line_strip(point_list, color, border_width, gl.GL_LINE_LOOP)

# --- END ELLIPSE FUNCTIONS # # #


# --- BEGIN LINE FUNCTIONS # # #

def _generic_draw_line_strip(point_list: PointList,
                             color: Color,
                             line_width: float=1,
                             mode: int=moderngl.LINE_STRIP):
    """
    Draw a line strip. A line strip is a set of continuously connected
    line segments.

    Args:
        :point_list: List of points making up the line. Each point is
         in a list. So it is a list of lists.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the line in pixels.
    Returns:
        None
    Raises:
        None
    """
    program = shader.program(
        vertex_shader=line_vertex_shader,
        fragment_shader=line_fragment_shader,
    )
    buffer_type = np.dtype([('vertex', '2f4'), ('color', '4B')])
    data = np.zeros(len(point_list), dtype=buffer_type)

    data['vertex'] = point_list

    color = get_four_byte_color(color)
    data['color'] = color

    vbo = shader.buffer(data.tobytes())
    vbo_desc = shader.BufferDescription(
        vbo,
        '2f 4B',
        ('in_vert', 'in_color'),
        normalized=['in_color']
    )

    vao_content = [vbo_desc]

    vao = shader.vertex_array(program, vao_content)
    with vao:
        program['Projection'] = get_projection().flatten()

        gl.glLineWidth(line_width)
        gl.glPointSize(line_width)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
        gl.glHint(gl.GL_POLYGON_SMOOTH_HINT, gl.GL_NICEST)

        vao.render(mode=mode)


def draw_line_strip(point_list: PointList,
                    color: Color, line_width: float=1):
    """
    Draw a multi-point line.

    Args:
        point_list:
        color:
        line_width:
    """
    _generic_draw_line_strip(point_list, color, line_width, gl.GL_LINE_STRIP)


def draw_line(start_x: float, start_y: float, end_x: float, end_y: float,
              color: Color, line_width: float=1):
    """
    Draw a line.

    Args:
        :start_x: x position of line starting point.
        :start_y: y position of line starting point.
        :end_x: x position of line ending point.
        :end_y: y position of line ending point.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the line in pixels.
    Returns:
        None
    Raises:
        None

    """

    points = (start_x, start_y), (end_x, end_y)
    draw_line_strip(points, color, line_width)


def draw_lines(point_list: PointList,
               color: Color,
               line_width: float=1):
    """
    Draw a set of lines.

    Draw a line between each pair of points specified.

    Args:
        :point_list: List of points making up the lines. Each point is
         in a list. So it is a list of lists.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the line in pixels.
    Returns:
        None
    Raises:
        None
    """

    _generic_draw_line_strip(point_list, color, line_width, gl.GL_LINES)


# --- BEGIN POINT FUNCTIONS # # #


def draw_point(x: float, y: float, color: Color, size: float):
    """
    Draw a point.

    Args:
        :x: x position of point.
        :y: y position of point.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :size: Size of the point in pixels.
    Returns:
        None
    Raises:
        None
    """
    point_list = [(x, y)]
    _generic_draw_line_strip(point_list, color, size, gl.GL_POINTS)


def draw_points(point_list: PointList,
                color: Color, size: float=1):
    """
    Draw a set of points.

    Args:
        :point_list: List of points Each point is
         in a list. So it is a list of lists.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :size: Size of the point in pixels.
    Returns:
        None
    Raises:
        None
    """
    _generic_draw_line_strip(point_list, color, size, gl.GL_POINTS)


# --- END POINT FUNCTIONS # # #

# --- BEGIN POLYGON FUNCTIONS # # #


def draw_polygon_filled(point_list: PointList,
                        color: Color):
    """
    Draw a polygon that is filled in.

    Args:
        :point_list: List of points making up the lines. Each point is
         in a list. So it is a list of lists.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
    Returns:
        None
    Raises:
        None
    """

    _generic_draw_line_strip(point_list, color, 1, gl.GL_POLYGON)


def draw_polygon_outline(point_list: PointList,
                         color: Color, line_width: float=1):
    """
    Draw a polygon outline. Also known as a "line loop."

    Args:
        :point_list: List of points making up the lines. Each point is
         in a list. So it is a list of lists.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: Width of the line in pixels.
    Returns:
        None
    Raises:
        None
    """
    _generic_draw_line_strip(point_list, color, line_width, gl.GL_LINE_LOOP)


def draw_triangle_filled(x1: float, y1: float,
                         x2: float, y2: float,
                         x3: float, y3: float, color: Color):
    """
    Draw a filled in triangle.

    Args:
        :x1: x value of first coordinate.
        :y1: y value of first coordinate.
        :x2: x value of second coordinate.
        :y2: y value of second coordinate.
        :x3: x value of third coordinate.
        :y3: y value of third coordinate.
        :color: Color of triangle.
    Returns:
        None
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_triangle_filled(1, 2, 3, 4, 5, 6, arcade.color.BLACK)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    first_point = (x1, y1)
    second_point = (x2, y2)
    third_point = (x3, y3)
    point_list = (first_point, second_point, third_point)
    draw_polygon_filled(point_list, color)


def draw_triangle_outline(x1: float, y1: float,
                          x2: float, y2: float,
                          x3: float, y3: float, color: Color,
                          border_width: float=1):
    """
    Draw a the outline of a triangle.

    Args:
        :x1: x value of first coordinate.
        :y1: y value of first coordinate.
        :x2: x value of second coordinate.
        :y2: y value of second coordinate.
        :x3: x value of third coordinate.
        :y3: y value of third coordinate.
        :color: Color of triangle.
        :border_width: Width of the border in pixels. Defaults to 1.
    Returns:
        None
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_triangle_outline(1, 2, 3, 4, 5, 6, arcade.color.BLACK, 5)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)

    """
    first_point = [x1, y1]
    second_point = [x2, y2]
    third_point = [x3, y3]
    point_list = (first_point, second_point, third_point)
    draw_polygon_outline(point_list, color, border_width)


# --- END POLYGON FUNCTIONS # # #


# --- BEGIN RECTANGLE FUNCTIONS # # #


def draw_lrtb_rectangle_outline(left: float, right: float, top: float,
                                bottom: float, color: Color,
                                border_width: float=1):
    """
    Draw a rectangle by specifying left, right, top, and bottom edges.

    Args:
        :left: The x coordinate of the left edge of the rectangle.
        :right: The x coordinate of the right edge of the rectangle.
        :top: The y coordinate of the top of the rectangle.
        :bottom: The y coordinate of the rectangle bottom.
        :color: The color of the rectangle.
        :border_width: The width of the border in pixels. Defaults to one.
    Returns:
        None
    Raises:
        :AttributeErrror: Raised if left > right or top < bottom.

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_lrtb_rectangle_outline(100, 100, 100, 100, \
        arcade.color.BLACK, 5)
    >>> arcade.draw_lrtb_rectangle_outline(190, 180, 100, 100, \
        arcade.color.BLACK, 5)
    Traceback (most recent call last):
        ...
    AttributeError: Left coordinate must be less than or equal to the right coordinate
    >>> arcade.draw_lrtb_rectangle_outline(170, 180, 100, 200, \
        arcade.color.BLACK, 5)
    Traceback (most recent call last):
        ...
    AttributeError: Bottom coordinate must be less than or equal to the top coordinate
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    if left > right:
        raise AttributeError("Left coordinate must be less than or equal to "
                             "the right coordinate")

    if bottom > top:
        raise AttributeError("Bottom coordinate must be less than or equal to "
                             "the top coordinate")

    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    width = right - left
    height = top - bottom
    draw_rectangle_outline(center_x, center_y, width, height, color,
                           border_width)


def draw_xywh_rectangle_outline(bottom_left_x: float, bottom_left_y: float,
                                width: float, height: float,
                                color: Color,
                                border_width: float=1):
    """
    Draw a rectangle extending from bottom left to top right

    Args:
        :bottom_left_x: The x coordinate of the left edge of the rectangle.
        :bottom_left_y: The y coordinate of the bottom of the rectangle.
        :width: The width of the rectangle.
        :height: The height of the rectangle.
        :color: The color of the rectangle.
        :border_width: The width of the border in pixels. Defaults to one.
    Returns:
        None
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_xywh_rectangle_outline(1, 2, 10, 10, arcade.color.BLACK, 5)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """
    center_x = bottom_left_x + (width / 2)
    center_y = bottom_left_y + (height / 2)
    draw_rectangle_outline(center_x, center_y, width, height, color,
                           border_width)


def draw_rectangle_outline(center_x: float, center_y: float, width: float,
                           height: float, color: Color,
                           border_width: float=1, tilt_angle: float=0):
    """
    Draw a rectangle outline.

    Args:
        :x: x coordinate of top left rectangle point.
        :y: y coordinate of top left rectangle point.
        :width: width of the rectangle.
        :height: height of the rectangle.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :border_width: width of the lines, in pixels.
        :angle: rotation of the rectangle. Defaults to zero.
    Returns:
        None
    Raises:
        None
    """

    p1 = -width // 2 + center_x, -height // 2 + center_y
    p2 = width // 2 + center_x, -height // 2 + center_y
    p3 = width // 2 + center_x, height // 2 + center_y
    p4 = -width // 2 + center_x, height // 2 + center_y

    if tilt_angle != 0:
        p1 = rotate_point(p1[0], p1[1], center_x, center_y, tilt_angle)
        p2 = rotate_point(p2[0], p2[1], center_x, center_y, tilt_angle)
        p3 = rotate_point(p3[0], p3[1], center_x, center_y, tilt_angle)
        p4 = rotate_point(p4[0], p4[1], center_x, center_y, tilt_angle)

    _generic_draw_line_strip((p1, p2, p3, p4), color, border_width, gl.GL_LINE_LOOP)


def draw_lrtb_rectangle_filled(left: float, right: float, top: float,
                               bottom: float, color: Color):
    """
    Draw a rectangle by specifying left, right, top, and bottom edges.

    Args:
        :left: The x coordinate of the left edge of the rectangle.
        :right: The x coordinate of the right edge of the rectangle.
        :top: The y coordinate of the top of the rectangle.
        :bottom: The y coordinate of the rectangle bottom.
        :color: The color of the rectangle.
        :border_width: The width of the border in pixels. Defaults to one.
    Returns:
        None
    Raises:
        :AttributeErrror: Raised if left > right or top < bottom.

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_lrtb_rectangle_filled(1, 2, 3, 1, arcade.color.BLACK)
    >>> arcade.draw_lrtb_rectangle_filled(2, 1, 3, 1, arcade.color.BLACK)
    Traceback (most recent call last):
        ...
    AttributeError: Left coordinate 2 must be less than or equal to the right coordinate 1
    >>> arcade.draw_lrtb_rectangle_filled(1, 2, 3, 4, arcade.color.BLACK)
    Traceback (most recent call last):
        ...
    AttributeError: Bottom coordinate 4 must be less than or equal to the top coordinate 3
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """
    if left > right:
        raise AttributeError("Left coordinate {} must be less than or equal "
                             "to the right coordinate {}".format(left, right))

    if bottom > top:
        raise AttributeError("Bottom coordinate {} must be less than or equal "
                             "to the top coordinate {}".format(bottom, top))

    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    width = right - left
    height = top - bottom
    draw_rectangle_filled(center_x, center_y, width, height, color)


def draw_xywh_rectangle_filled(bottom_left_x: float, bottom_left_y: float,
                               width: float, height: float,
                               color: Color):
    """
    Draw a filled rectangle extending from bottom left to top right

    Args:
        :bottom_left_x: The x coordinate of the left edge of the rectangle.
        :bottom_left_y: The y coordinate of the bottom of the rectangle.
        :width: The width of the rectangle.
        :height: The height of the rectangle.
        :color: The color of the rectangle.
    Returns:
        None
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> arcade.draw_xywh_rectangle_filled(1, 2, 3, 4, arcade.color.BLACK)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    center_x = bottom_left_x + (width / 2)
    center_y = bottom_left_y + (height / 2)
    draw_rectangle_filled(center_x, center_y, width, height, color)


def draw_rectangle_filled(center_x: float, center_y: float, width: float,
                          height: float, color: Color,
                          tilt_angle: float=0):
    """
    Draw a filled-in rectangle.

    Args:
        :center_x: x coordinate of rectangle center.
        :center_y: y coordinate of rectangle center.
        :width: width of the rectangle.
        :height: height of the rectangle.
        :color: color, specified in a list of 3 or 4 bytes in RGB or
         RGBA format.
        :angle: rotation of the rectangle. Defaults to zero.

    Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_rectangle_filled(390, 150, 45, 105, arcade.color.BLUSH)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """
    p1 = -width // 2 + center_x, -height // 2 + center_y
    p2 = width // 2 + center_x, -height // 2 + center_y
    p3 = width // 2 + center_x, height // 2 + center_y
    p4 = -width // 2 + center_x, height // 2 + center_y

    if tilt_angle != 0:
        p1 = rotate_point(p1[0], p1[1], center_x, center_y, tilt_angle)
        p2 = rotate_point(p2[0], p2[1], center_x, center_y, tilt_angle)
        p3 = rotate_point(p3[0], p3[1], center_x, center_y, tilt_angle)
        p4 = rotate_point(p4[0], p4[1], center_x, center_y, tilt_angle)

    _generic_draw_line_strip((p1, p2, p4, p3), color, 1, gl.GL_TRIANGLE_STRIP)


def draw_texture_rectangle(center_x: float, center_y: float, width: float,
                           height: float, texture: Texture, angle: float=0,
                           alpha: float=1, transparent: bool=True,
                           repeat_count_x=1, repeat_count_y=1):
    """
    Draw a textured rectangle on-screen.

    Args:
        :center_x: x coordinate of rectangle center.
        :center_y: y coordinate of rectangle center.
        :width: width of the rectangle.
        :height: height of the rectangle.
        :texture: identifier of texture returned from load_texture() call
        :angle: rotation of the rectangle. Defaults to zero.
        :alpha: Transparency of image.
    Returns:
        None
    Raises:
        None

    :Example:

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.set_background_color(arcade.color.WHITE)
    >>> arcade.start_render()
    >>> arcade.draw_text("draw_bitmap", 483, 3, arcade.color.BLACK, 12)
    >>> name = "arcade/examples/images/playerShip1_orange.png"
    >>> texture = arcade.load_texture(name)
    >>> scale = .6
    >>> arcade.draw_texture_rectangle(540, 120, scale * texture.width, \
scale * texture.height, texture, 0)
    >>> arcade.draw_texture_rectangle(540, 60, scale * texture.width, \
scale * texture.height, texture, 90)
    >>> arcade.draw_texture_rectangle(540, 60, scale * texture.width, \
scale * texture.height, texture, 90, 1, False)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    texture.draw(center_x, center_y, width,
                 height, angle, alpha,
                 repeat_count_x, repeat_count_y)


def draw_xywh_rectangle_textured(bottom_left_x: float, bottom_left_y: float,
                                 width: float, height: float,
                                 texture: Texture, angle: float=0,
                                 alpha: float=1, transparent: bool=True,
                                 repeat_count_x=1, repeat_count_y=1):
    """
    Draw a texture extending from bottom left to top right.

    Args:
        :bottom_left_x: The x coordinate of the left edge of the rectangle.
        :bottom_left_y: The y coordinate of the bottom of the rectangle.
        :width: The width of the rectangle.
        :height: The height of the rectangle.
        :texture: identifier of texture returned from load_texture() call
        :angle: rotation of the rectangle. Defaults to zero.
        :alpha: Transparency of image.
    Returns:
        None
    Raises:
        None

    >>> import arcade
    >>> arcade.open_window(800,600,"Drawing Example")
    >>> arcade.start_render()
    >>> name = "arcade/examples/images/meteorGrey_big1.png"
    >>> texture1 = load_texture(name, 1, 1, 50, 50)
    >>> arcade.draw_xywh_rectangle_textured(1, 2, 10, 10, texture1)
    >>> arcade.finish_render()
    >>> arcade.quick_run(0.25)
    """

    center_x = bottom_left_x + (width / 2)
    center_y = bottom_left_y + (height / 2)
    draw_texture_rectangle(center_x, center_y, width, height, texture, angle, alpha, transparent, repeat_count_x,
                           repeat_count_y)


def get_pixel(x: int, y: int):
    """
    Given an x, y, will return RGB color value of that point.
    """
    a = (gl.GLubyte * 3)(0)
    gl.glReadPixels(x, y, 1, 1, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, a)
    red = a[0]
    green = a[1]
    blue = a[2]
    return (red, green, blue)


def get_image(x=0, y=0, width=None, height=None):
    """
    Get an image from the screen.
    You can save the image like:

    image = get_image()
    image.save('screenshot.png', 'PNG')
    """

    # Get the dimensions
    window = get_window()
    if width is None:
        width = window.width - x
    if height is None:
        height = window.height - y

    # Create an image buffer
    image_buffer = (gl.GLubyte * (4 * width * height))(0)

    gl.glReadPixels(x, y, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, image_buffer)
    image = PIL.Image.frombytes("RGBA", (width, height), image_buffer)
    image = PIL.ImageOps.flip(image)

    # image.save('glutout.png', 'PNG')
    return image
