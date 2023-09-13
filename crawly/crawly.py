import pygame
from math import cos, sin, radians
from enum import Enum
from functools import partial
import threading
import time


# Queue. popping has a cooldown.
class TimedQueue:
    def __init__(self, cooldown):
        self.elements = []
        self.cooldown = cooldown / 1000.0 # Convert millis to secs
        self.time_since = 0.0
        self.t = 0.0

    def set_cooldown(self, cool):
        self.cooldown = cool / 1000.0

    def push(self, el):
        self.elements.append(el)

    def _pop(self):
        try:
            el = self.elements[0]
            self.elements.remove(el)
        except IndexError:
            return None
        return el

    def pop(self):
        """
        Will not pop from queue unless queue cooldown is over.
        """
        t = time.time()
        self.time_since += time.time() - self.t
        self.t = t

        if self.time_since > self.cooldown:
            self.time_since = 0.0
            return self._pop()
        return None


# Create a global object for the file to hold all state data
class Data:
    def __init__(self):
        self.ms = 1000
        self.color = "black"
        self.text_color = "black"
        self.screen = None
        self.background = "white"
        self.poly_width = 0
        self.poly_points = []
        self.draw_list = []
        self.background_list = []
        self.draw_background = False

        # Changes
        self.setup_complete = False
        self.render_commands = TimedQueue(self.ms)
        self.done = False
        self.running = False
        self.pygame_thread = None
        self.thread_lock = None


# Global object to store state
data = Data()


# Enum for rotating rectangles to identify the rotation point
class RotationPoint(Enum):
    '''
        Rotation points specifies the point about which an object will be rotated

        Attributes:
            BOTTOM_LEFT
            BOTTOM_RIGHT
            TOP_LEFT
            TOP_RIGHT
            CENTER
    '''
    BOTTOM_LEFT = 0
    '''Rotate about the bottom left corner'''
    BOTTOM_RIGHT = 1
    '''Rotate about the bottom right corner'''
    TOP_RIGHT = 2
    '''Rotate about the top right corner'''
    TOP_LEFT = 3
    '''Rotate about the top left corner'''
    CENTER = 4
    '''Rotate about the center'''

def pygame_loop(title, dimensions, background):
    # Setup
    with data.thread_lock:
        data.background = background
        pygame.init()
        data.screen = pygame.display.set_mode(dimensions)
        data.screen.fill(background)
        pygame.display.set_caption(title)
        pygame.display.flip()
        pygame.event.wait()  # Ensure the window is not behind another window

        # Complete setup so main thread can continue
        data.setup_complete = True

    # Window Loop
    while data.running:
        # Rendering
        with data.thread_lock:
            el = data.render_commands.pop()
            if el:
                comm, args = el
                comm(*args)

        # poll for events
        for event in pygame.event.get():
            with data.thread_lock:
                if event.type == pygame.QUIT and data.done:
                    data.running = False
    pygame.quit()


# First call always made
def start(title="Welcome to Painter", dimensions=(1280, 720), background="white"):
    """
        Must be called before any other Drawly functions in order to create the window.

        Args:
            title (str): (Optional) Title of the Drawly window
            dimensions ((int, int)): (Optional) Tuple of the dimensions of the window. 1280x720 default
            background (str): (Optional) Background color of the window. White by default
    """
    data.running = True
    data.thread_lock = threading.Lock()
    data.pygame_thread = threading.Thread(target=pygame_loop, args=(title, dimensions, background))
    data.pygame_thread.start()

    # Important because we can't try to access pygame objects until they are set up (or else errors).
    while not data.setup_complete: # wait for the pygame thread to complete setup
        continue

    data.setup_complete = False # Reset so that a future drawly.start() call will work after drawly.done()


# Change the speed at which paint draws. Sets the approximate frame rate. The draw() functions will not
# draw faster than the frame rate
def set_speed(speed):
    """
        Set the speed for drawing. Each time draw() or redraw() is called there will be a delay based on
            the speed value. 1 is slow, approximately 1 frame every 2 seconds. 10 is approximately 30 frames per second
        Args:
            speed (int): Rate at which drawings are rendered on the screen
    """
    if speed < 1:
        speed = 1
    elif speed > 10:
        speed = 10
    data.ms = 33 + 197 * (10 - speed)
    data.render_commands.set_cooldown(data.ms)


# Change the color that will be used
def set_color(new_color):
    """
        Change the color for future drawings.

        Args:
            new_color (str): Color to use
    """
    data.color = new_color


# Draw all items that have been created since the last call to paint()
def draw():
    """
        Draws all items created since the last call of draw()
    """
    with data.thread_lock:
        ls = data.draw_list.copy()
        data.render_commands.push([do_draw, (False, ls,)])
        data.draw_list.clear()


# Erase all items then draw new items that have been created since the last call to draw()
def redraw():
    """
        Draws all items created since the last call of draw()
    """
    with data.thread_lock:
        ls = data.draw_list
        data.render_commands.push([do_draw, (True, ls,)])
        data.draw_list.clear()


def do_draw(refresh, draw_list):
    # Clear the screen and draw the background on a redraw
    if refresh:
        data.screen.fill(data.background)
        for i in data.background_list:
            i()

    # Draw the current list of items since last draw
    for i in draw_list:
        try:
            i()
        except Exception as e:
            # This just means this one item can't be drawn. would be cool to log this instead of print to the console.
            print("ERROR::RENDER_ERROR: Could not execute pygame render command!\n    " + str(e))

    # Clear the draw list
    draw_list.clear()

    pygame.display.flip()


# draw a circle with a center at x_pos, y_pos
def circle(x_pos, y_pos, radius, stroke=0):
    """
        Creates a circle to be drawn on the screen. The circle will be drawn the next time draw() is called.


        Args:
            x_pos (int): X-coordinate of the center of the circle
            y_pos (int): Y-coordinate of the center of the circle
            radius (int): Radius of the circle
            stroke (int): (Optional) Default is 0, which is a filled circle. Otherwise is the size of outline stroke
    """
    add_draw_item(partial(pygame.draw.circle, data.screen, data.color, [x_pos, y_pos], radius, width=stroke))


# Draw a rectangle with an optional rotation and rotation point
"""
    Borrowed some of this code from online and will credit if I ever find the place again. :)
    - rotation_angle: in degree
    - rotation_offset_center: moving the center of the rotation: (-100,0) will turn the rectangle around a point 100 above center of the rectangle,
                                         if (0,0) the rotation is at the center of the rectangle
    - nAntialiasingRatio: set 1 for no antialising, 2/4/8 for better aliasing
"""


def rectangle(x_pos, y_pos, width, height, stroke=0, rotation_angle=0, rotation_point=RotationPoint.CENTER):
    """
        Creates a rectangle to be drawn on the screen.

        Args:
            x_pos (int): X-coordinate of the top left of the unrotated rectangle
            y_pos (int): Y-coordinate of the top left of the unrotated rectangle
            width (int): Width of the unrotated rectangle (x-direction)
            height (int): Height of the unrotated rectangle (y-direction)
            stroke (int): 0 for a filled rectangle. > 0 is  the width of the line drawn. Default is 0.
            rotation_angle (int): Degrees to rotate the rectangle. Default is 0
            rotation_point: (RotationPoint): Point to rotate the rectangle about
    """
    nRenderRatio = 8

    # the rotation point is relative to the center of the rectangle
    if rotation_point == RotationPoint.CENTER:
        rotation_offset_center = (0, 0)
    elif rotation_point == RotationPoint.BOTTOM_LEFT:
        rotation_offset_center = (-width // 2, height // 2)
    elif rotation_point == RotationPoint.BOTTOM_RIGHT:
        rotation_offset_center = (width // 2, height // 2)
    elif rotation_point == RotationPoint.TOP_RIGHT:
        rotation_offset_center = (width // 2, -height // 2)
    elif rotation_point == RotationPoint.TOP_LEFT:
        rotation_offset_center = (-width // 2, -height // 2)
    else:  # manually enter a point as a tuple
        x_pt, y_pt = rotation_point
        rotation_offset_center = (x_pt - x_pos - width // 2, y_pt - y_pos - height // 2)

    sw = width + abs(rotation_offset_center[0]) * 2
    sh = height + abs(rotation_offset_center[1]) * 2

    surfcenterx = sw // 2
    surfcentery = sh // 2
    s = pygame.Surface((sw * nRenderRatio, sh * nRenderRatio))
    s = s.convert_alpha()
    s.fill((0, 0, 0, 0))

    rw2 = width // 2  # halfwidth of rectangle
    rh2 = height // 2

    pygame.draw.rect(s, data.color, ((surfcenterx - rw2 - rotation_offset_center[0]) * nRenderRatio,
                                     (surfcentery - rh2 - rotation_offset_center[1]) * nRenderRatio,
                                     width * nRenderRatio,
                                     height * nRenderRatio), stroke * nRenderRatio)
    s = pygame.transform.rotate(s, rotation_angle)
    if nRenderRatio != 1: s = pygame.transform.smoothscale(s, (
        s.get_width() // nRenderRatio, s.get_height() // nRenderRatio))
    incfromrotw = (s.get_width() - sw) // 2
    incfromroth = (s.get_height() - sh) // 2
    add_draw_item(partial(data.screen.blit, s, (x_pos - surfcenterx + rotation_offset_center[0] + rw2 - incfromrotw,
                                                y_pos - surfcentery + rotation_offset_center[1] + rh2 - incfromroth)))


# Draw a line with a starting point, length, and angle. The angle is the heading given in degrees based on the unit circle
def vector(x_pos, y_pos, length, angle=0, stroke=1):
    """
        Draws a line based on a starting point, length, angle, and stroke size (width of line)

        Args:
            x_pos (int): X-coordinate of the start of the line
            y_pos (int): Y-coordinate of the start of the line
            length (int): Length of the line to draw
            angle (int): (Optional) Direction of line in degrees. 0 degrees is horizontal to the right. Default is 0
            stroke (int): (Optional) Width of the line drawn. Default is 1
    """
    end_x = x_pos + length * cos(radians(-angle))  # use negative to match with unit circle
    end_y = y_pos + length * sin(radians(-angle))
    add_draw_item(partial(pygame.draw.line, data.screen, data.color, (x_pos, y_pos), (end_x, end_y), stroke))


# Draw a line with a starting point and end point
def line(x_pos1, y_pos1, x_pos2, y_pos2, stroke=1):
    """
       Draws a line based on a starting point, end point, and stroke size (width of line)

       Args:
           x_pos1 (int): X-coordinate of the start of the line
           y_pos1 (int): Y-coordinate of the start of the line
           x_pos2(int): X-coordinate of the end of the line
           y_pos2 (int): Y-coordinate of the end of the line
           stroke (int): (Optional) Width of the line drawn. Default is 1
   """
    add_draw_item(partial(pygame.draw.line, data.screen, data.color, (x_pos1, y_pos1), (x_pos2, y_pos2), stroke))


# Call when starting to define a polygon. Width=0 is filled. Otherwise is a stroke size
def polygon_begin(stroke=0):
    """
       Call to begin creating a polygon. Call add_poly_points to create the polygon

       Args:
           stroke (int): 0 for a filled rectangle. > 0 is  the width of the line drawn. Default is 0.
   """
    data.poly_width = stroke
    data.poly_points.clear()


# Add points for the polygon. Must be called after begin and before end
def add_poly_point(x_pos, y_pos):
    """
       Add a point to the polygon to be drawn.

       Args:
           x_pos (int): X-position of the point to add
           y_pos (int): Y-position of the point to add
   """
    data.poly_points.append([x_pos, y_pos])


# Call after adding points to the polygon to draw it
def polygon_end():
    """
        Call to end the creation of the polygon.
    """
    add_draw_item(partial(pygame.draw.polygon, data.screen, data.color, data.poly_points.copy(), data.poly_width))


# Define a rectangle that an ellipse will fit in.
def ellipse(x_pos, y_pos, width, height, stroke=0):
    """
       Draws an ellipse inside of the defined rectangle

       Args:
            x_pos (int): X-coordinate of the top left
            y_pos (int): Y-coordinate of the top left
            width (int): Width of the rectangle (x-direction)
            height (int): Height of the rectangle (y-direction)
            stroke (int): 0 for a filled rectangle. > 0 is  the width of the line drawn. Default is 0.
    """
    add_draw_item(partial(pygame.draw.ellipse, data.screen, data.color, (x_pos, y_pos, width, height), stroke))


# Define a rectangle that an ellipse will fit in. Start and end are the degree points where the line will be drawn
def arc(x_pos, y_pos, width, height, start, end, stroke=1):
    """
       Draws an ellipse arc inside of the defined rectangle

       Args:
            x_pos (int): X-coordinate of the top left
            y_pos (int): Y-coordinate of the top left
            width (int): Width of the rectangle (x-direction)
            height (int): Height of the rectangle (y-direction)
            start (int): Degree point on arc to begin drawing
            end (int): Degree point on arc to end drawing
            stroke (int): 0 for a filled rectangle. > 0 is  the width of the line drawn. Default is 0.
    """
    add_draw_item(
        partial(pygame.draw.arc, data.screen, data.color, (x_pos, y_pos, width, height), radians(start), radians(end),
    stroke))


# Write some text.
def text(x_pos, y_pos, text, size=20):
    """
       Draws text on the screen.

       Args:
            x_pos (int): X-coordinate of the top left of the text
            y_pos (int): Y-coordinate of the top left of the text
            text (str): Text to write
            size (int): (Optional) Font size. Default is 20
    """
    text_font = pygame.font.SysFont("timesnewroman", size).render(text, True, data.color)
    add_draw_item(partial(data.screen.blit, text_font, (x_pos, y_pos)))


# Call when adding items to the background image
def background_begin():
    data.draw_background = True


# Call when done adding items to the background image
def background_end():
    data.draw_background = False


# Add a drawing function to the appropriate list
def add_draw_item(draw_function):
    if data.draw_background:
        data.background_list.append(draw_function)
    data.draw_list.append(draw_function)


# Call when done so window doesn't close. Click on X to close
def done():
    """
       Call at the end of the program so the window stays until it is closed by the user
    """
    with data.thread_lock:
        data.done = True

    data.pygame_thread.join()

