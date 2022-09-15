'''
Display a gaze marker inside a screen.
Demonstates how to create a window which displays markers and map gaze data into the given window
'''

import math
import sys
from collections import deque

import cv2
import cv2.aruco as aruco # pylint: disable=no-member, import-error
import numpy as np

# This example requires the PySide2 library for displaying windows and video. Other such libraries are avaliable, and
# you are free to use whatever you'd like for your projects.
from PySide2 import QtCore, QtGui, QtWidgets

import adhawkapi
import adhawkapi.frontend
from adhawkapi.publicapi import Events, MarkerSequenceMode, PacketType


GAZE_MARKER_SIZE = 20


class Frontend:
    '''
    Frontend communicating with the backend
    '''

    def __init__(self, handle_camera_start_response, handle_gaze_in_screen_stream):
        # Instantiate an API object
        self._api = adhawkapi.frontend.FrontendApi()

        # Save the given handler to pass in when we start the camera
        self._handle_camera_start_response = handle_camera_start_response

        # Tell the api that we wish to tap into the GAZE_IN_SCREEN in screen data stream
        # with the given handle_gaze_in_screen_stream as the handler
        self._api.register_stream_handler(PacketType.GAZE_IN_SCREEN, handle_gaze_in_screen_stream)

        # Tell the api that we wish to tap into the EVENTS stream
        # with self._handle_event_stream as the handler
        self._api.register_stream_handler(PacketType.EVENTS, self._handle_event_stream)

        # Start the api and set its connection callback to self._handle_connect. When the api detects a connection to a
        # MindLink, this function will be run.
        self._api.start(connect_cb=self._handle_connect_response)

    def shutdown(self):
        ''' Shuts down the backend connection '''

        # Disables screen tracking
        self.enable_screen_tracking(False)

        # Stops api camera capture
        self._api.stop_camera_capture(lambda *_args: None)

        # Stop the log session
        self._api.stop_log_session(lambda *_args: None)

        # Shuts down the api
        self._api.shutdown()
        print('Shut down api')

    def quickstart(self):
        ''' Runs a Quick Start using AdHawk Backend's GUI '''

        # The tracker's camera will need to be running to detect the marker that the Quick Start procedure will display
        self._api.quick_start_gui(mode=MarkerSequenceMode.FIXED_GAZE, marker_size_mm=35,
                                  callback=(lambda *_args: None))

    def calibrate(self):
        ''' Calibrates the gaze tracker using AdHawk Backend's GUI '''

        # Two calibration modes are supported: FIXED_HEAD and FIXED_GAZE
        # With fixed head mode you look at calibration markers without moving your head
        # With fixed gaze mode you keep looking at a central point and move your head as instructed during calibration
        self._api.start_calibration_gui(mode=MarkerSequenceMode.FIXED_HEAD, n_points=9, marker_size_mm=35,
                                        randomize=False, callback=(lambda *_args: None))

    def register_screen(self, screen_width, screen_height, aruco_dic, marker_ids, markers):
        ''' Registers the screen and starts tracking on a successful discovery'''

        # Tells the api to search for the screen displaying ArUco (tracking) markers with the given parameters.
        # We set self._handle_screen_registered_response as the handler for the api's response to this request.
        self._api.register_screen_board(screen_width, screen_height, aruco_dic, marker_ids, markers,
                                        self._handle_screen_registered_response)

    def enable_screen_tracking(self, enable):
        ''' Utility function to enable or disable screen tracking '''

        # Note that the GAZE_IN_SCREEN data stream will only output when screen tracking is enabled
        if enable:
            print('Starting screen tracking')
            self._api.start_screen_tracking(lambda *_args: None)
        else:
            print('Stopping screen tracking')
            self._api.stop_screen_tracking(lambda *_args: None)

    def _handle_event_stream(self, event_type, _timestamp, *_args):
        ''' Handler for the event stream '''

        if event_type == Events.PROCEDURE_ENDED:

            # Screen tracking gets disabled when we start a marker sequence procedure, such as a Quick Start or
            # calibration, so we re-enable it upon receiving a PROCEDURE_ENDED event
            self.enable_screen_tracking(True)

    def _handle_connect_response(self, error):
        ''' Handler for backend connection responses '''

        # Starts the camera and sets the rate for relevant streams
        if not error:
            print('Backend connected')

            # Sets the GAZE_IN_SCREEN data stream rate to 125Hz
            self._api.set_stream_control(adhawkapi.PacketType.GAZE_IN_SCREEN, 125, callback=(lambda *args: None))

            # Tells the api which event streams we want to tap into, in this case the PROCEDURE_START_END stream
            self._api.set_event_control(adhawkapi.EventControlBit.PRODECURE_START_END, 1, callback=(lambda *args: None))

            # Starts the tracker's camera so that video can be captured and sets self._handle_camera_start_response as
            # the callback. This function will be called once the api has finished starting the camera.
            self._api.start_camera_capture(camera_index=0, resolution_index=adhawkapi.CameraResolution.MEDIUM,
                                           correct_distortion=False, callback=self._handle_camera_start_response)

            # Starts a logging session which saves eye tracking signals. This can be very useful for troubleshooting
            self._api.start_log_session(log_mode=adhawkapi.LogMode.BASIC, callback=lambda *args: None)


    def _handle_screen_registered_response(self, error):
        ''' Handler for the screen register response '''

        # If the screen was registered successfully, we enable screen tracking to start the GAZE_IN_SCREEN stream
        if not error:
            print('ArUco markers registered')
            self.enable_screen_tracking(True)


class TrackingWindow(QtWidgets.QWidget):
    ''' Class for receiving and displaying the user's gaze in the screen '''
    # pylint: disable=too-many-instance-attributes
    MARKER_DIC = cv2.aruco.DICT_4X4_50  # pylint: disable=no-member
    ARUCO_MARKER_SIZE_MM = 20
    ARUCO_MARKER_BORDER_MM = 1
    EDGE_OFFSETS_MM = np.array([[10, 10], [10, 10]])  # Marker offsets: [[left, right], [top, bottom]]

    NUM_POINTS = 10

    def __init__(self):
        QtWidgets.QWidget.__init__(self)
        self.setWindowTitle('Screen tracking example')

        # Gets the screen dpi from Qt's QApplication class
        dpi_x = QtWidgets.QApplication.instance().primaryScreen().physicalDotsPerInchX()
        dpi_y = QtWidgets.QApplication.instance().primaryScreen().physicalDotsPerInchY()

        # Calculates the 'real' dpi as the average of the horizontal and vertical dpis
        self._dpi = np.mean([dpi_x, dpi_y])

        # Use the entire screen
        self._screen_size = np.array([QtWidgets.QApplication.instance().primaryScreen().geometry().width(),
                                      QtWidgets.QApplication.instance().primaryScreen().geometry().height()])

        # Gets the screen size in mm and outputs all screen information to the console
        self._screen_size_mm = self._pix_to_mm(self._screen_size)
        print(f'screen info: \n    dpi={self._dpi}\n    size_pix={self._screen_size}\n    size_mm={self._screen_size_mm}')

        # Unique IDs for each ArUco (tracking) marker
        self._marker_ids = [0, 1, 2, 3]

        # Calculate the position of the markers on the screen
        self._marker_positions = self._calculate_marker_positions()

        # Takes the marker positions and generates an RGBA OpenCV image
        marker_image = self._create_marker_image()

        # Convert the RGBA buffer into a Qt Label widget
        self._marker_widget = QtWidgets.QLabel()
        qt_marker_image = QtGui.QImage(marker_image, marker_image.shape[1], marker_image.shape[0],
                                       marker_image.shape[1] * marker_image.shape[2], QtGui.QImage.Format_ARGB32)
        self._marker_pixmap = QtGui.QPixmap(qt_marker_image)
        self._marker_widget.setPixmap(self._marker_pixmap)

        # Text instruction layer / widget
        text_label = QtWidgets.QLabel()
        text_label.setText('ESC: Exit\nQ: Run a Quick Start\nC: Run a Calibration')
        text_label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)

        # Example background layer / widget
        background_widget = QtWidgets.QLabel()
        background_widget.setStyleSheet("background-color:lightblue")

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(background_widget, 0, 0)
        layout.addWidget(self._marker_widget, 0, 0)
        layout.addWidget(text_label, 0, 0)

        # A Quick Start tunes the scan range and frequency to best suit the user's eye and face shape, resulting in
        # better tracking data. For the best quality results in your application, you should also perform a calibration
        # before using gaze data.
        self.quickstart_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence('q'), self)
        self.quickstart_shortcut.activated.connect(self._quickstart)

        # A calibration allows us to relate the measured gaze with the real world using a series of markers displayed
        # in known positions
        self.calibration_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence('c'), self)
        self.calibration_shortcut.activated.connect(self._calibrate)

        self.calibration_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence('Escape'), self)
        self.calibration_shortcut.activated.connect(self.close)

        self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
        self.showMaximized()

        # Deque for storing the most recent gaze points, which is currently needed to reduce jitter
        self._point_deque = deque()

        self._running_xcoord = 0
        self._running_ycoord = 0

        self._xcoord = None
        self._ycoord = None

        # Creates the Frontend object
        self.frontend = Frontend(self._handle_camera_start_response, self._handle_gaze_in_screen_stream)

        self._setup_video_timer()

    def _setup_video_timer(self):
        self._imagetimer_interval = 1000 / 60
        self._imagetimer = QtCore.QTimer()
        self._imagetimer.timeout.connect(self._every_frame)
        self._imagetimer.start(self._imagetimer_interval)

    def _handle_gaze_in_screen_stream(self, _timestamp, xpos, ypos):
        ''' Handler for the gaze in screen stream '''
        if math.isnan(xpos) or math.isnan(ypos):
            return

        # Translates the passed coordinates to positions on the screen
        new_xcoord = round(self._screen_size[0] * xpos)
        new_ycoord = round(self._screen_size[1] * ypos)

        # Adds the new point to the point deque, and pops the least recent entry if the size of the deque exceeds
        # its maximum allowed size
        old_xcoord = 0
        old_ycoord = 0
        self._point_deque.append((new_xcoord, new_ycoord))
        if len(self._point_deque) > self.NUM_POINTS:
            (old_xcoord, old_ycoord) = self._point_deque.popleft()

        # Calculates display coordinates as an average of all points in the deque (reduces jitter)
        self._running_xcoord += new_xcoord - old_xcoord
        self._running_ycoord += new_ycoord - old_ycoord

        self._xcoord = self._running_xcoord / len(self._point_deque)
        self._ycoord = self._running_ycoord / len(self._point_deque)

    def _every_frame(self):
        if not self._xcoord or not self._ycoord:
            return

        pixmap = self._marker_pixmap.copy()

        # Qt code to draw a circle at the calculated position
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 0, 0), QtCore.Qt.SolidPattern))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(QtCore.QRectF(self._xcoord - GAZE_MARKER_SIZE / 2,
                                          self._ycoord - GAZE_MARKER_SIZE / 2,
                                          GAZE_MARKER_SIZE, GAZE_MARKER_SIZE))
        painter.end()

        # Sets the new image with the gaze marker ellipse drawn
        self._marker_widget.setPixmap(pixmap)

    def _handle_camera_start_response(self, error):
        ''' Handler for the camera start response '''

        # If the camera started successfully, we try to register the screen.
        if not error:
            print('Camera started')
            self.frontend.register_screen(self._screen_size_mm[0] * 1e-3, self._screen_size_mm[1] * 1e-3,
                                          self.MARKER_DIC, self._marker_ids, self._marker_positions)

    def _mm_to_pix(self, length_mm):
        ''' Converts an array of values in mm to an aray of pixel lengths '''
        mm2inch = 25.4
        return (np.array(length_mm) * self._dpi / mm2inch).astype(int)

    def _pix_to_mm(self, length_pix):
        ''' Converts an array of pixel lengths to an array of values in mm '''
        mm2inch = 25.4
        return np.array(length_pix) * mm2inch / self._dpi

    def _calculate_marker_positions(self):
        ''' Calculates up the positions of the ArUco markers on the screen '''
        margin_size = self.EDGE_OFFSETS_MM * 1e-3
        screen_size = self._screen_size_mm * 1e-3
        marker_size = self.ARUCO_MARKER_SIZE_MM * 1e-3

        positions = np.array([
            [margin_size[0, 0], - margin_size[1, 0] - marker_size],
            [screen_size[0] - margin_size[0, 1] - marker_size, - margin_size[1, 0] - marker_size],
            [margin_size[0, 0], - screen_size[1] + margin_size[1, 1]],
            [screen_size[0] - margin_size[0, 1] - marker_size, - screen_size[1] + margin_size[1, 1]],
        ])
        markers = []
        for marker_pos in positions:
            markers.append([*marker_pos, marker_size])
        return markers

    def _create_marker_image(self):
        ''' Uses the calculated marker positions to draw ArUco markers to an image '''

        marker_size = int(self._screen_size[0] * self.ARUCO_MARKER_SIZE_MM / self._screen_size_mm[0])
        margins = self._mm_to_pix(self.EDGE_OFFSETS_MM)
        board_image = np.zeros((self._screen_size[1], self._screen_size[0], 4), dtype=np.uint8)

        offsets = {0: (margins[0, 0], margins[1, 0]),
                   1: (self._screen_size[0] - margins[0, 1] - marker_size, margins[1, 0]),
                   2: (margins[0, 0], self._screen_size[1] - margins[1, 1] - marker_size),
                   3: (self._screen_size[0] - margins[0, 1] - marker_size,
                       self._screen_size[1] - margins[1, 1] - marker_size)}

        for _id_i, _id in enumerate(self._marker_ids):
            _img = np.full((marker_size, marker_size), 255, dtype=np.uint8)
            aruco.drawMarker(aruco.Dictionary_get(self.MARKER_DIC), _id, marker_size, _img, 1)
            _img = cv2.cvtColor(_img, cv2.COLOR_GRAY2RGBA)
            board_image[offsets[_id_i][1]:offsets[_id_i][1] + marker_size,
                        offsets[_id_i][0]:offsets[_id_i][0] + marker_size] = _img

            border_thickness = self._mm_to_pix(self.ARUCO_MARKER_BORDER_MM)
            border_start = (offsets[_id_i][0] - border_thickness, offsets[_id_i][1] - border_thickness)
            border_end = (offsets[_id_i][0] + marker_size, offsets[_id_i][1] + marker_size)
            board_image = cv2.rectangle(board_image, border_start, border_end, (255, 255, 255, 255), border_thickness)

        return board_image

    def _calibrate(self):
        ''' Function to allow the main loop to invoke a Calibration '''
        self.frontend.enable_screen_tracking(False)
        self.frontend.calibrate()

    def _quickstart(self):
        ''' Function to allow the main loop to invoke a Quick Start '''
        self.frontend.enable_screen_tracking(False)
        self.frontend.quickstart()

    def closeEvent(self, event):
        ''' Override of closeEvent method to shut down the api when the window closes '''
        super().closeEvent(event)
        self.frontend.shutdown()


def main():
    ''' Main function '''
    app = QtWidgets.QApplication(sys.argv)
    TrackingWindow()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
