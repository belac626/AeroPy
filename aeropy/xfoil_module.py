"""XFOIL Python interface."""
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#                       Import necessary modules
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
import datetime
import math
import os  # To check for already existing files and delete them
import platform as pf
import shutil  # Modules necessary for saving multiple plots
import subprocess as sp
import time
from queue import Empty, Queue
from threading import Thread

import numpy as np

# Created on Mar  9 14:58:25 2014
# Last update Jul 20 16:26:40 2015
# @author: Pedro Leal

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#                     Classes for reading xfoil output
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


class NonBlockingStreamReader:
    """Create readable subprocess stream on separate thread.

    http://eyalarubas.com/python-subproc-nonblock.html
    """

    def __init__(self, stream):
        """Instantiate.

        stream: the stream to read from.
                Usually a process' stdout or stderr.
        """
        self._s = stream
        self._q = Queue()

        def _populateQueue(stream, queue):
            """Collect lines from 'stream' and put them in 'queue'."""
            while True:
                line = stream.readline()
                try:  # if line:
                    queue.put(line)
                except UnexpectedEndOfStream:  # else:
                    pass  # raise UnexpectedEndOfStream

        self._t = Thread(target=_populateQueue, args=(self._s, self._q))
        self._t.daemon = True
        self._t.start()  # start collecting lines from the stream

    def readline(self, timeout=None):
        """Read non-blocked stream from subprocess in thread."""
        try:
            return self._q.get(block=timeout is not None, timeout=timeout)
        except Empty:
            return None


class UnexpectedEndOfStream(Exception):
    """Exception for queue population error."""

    pass


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#                           Core Functions
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


def call(airfoil, indir='', outdir='', alfas='none', output='Cp',  # noqa C901
         Reynolds=0, Mach=0,
         plots=False, echo=False, NACA=True, GDES=False, iteration=10,
         flap=None, PANE=False, NORM=True):
    """Call xfoil through Python.

    The input variables are:

    :param airfoil: if NACA is false, airfoil is the name of the plain
           filewhere the airfoil geometry is stored (variable airfoil).
           If NACA is True, airfoil is the naca series of the airfoil
           (i.e.: naca2244). By default NACA is False.

    :param dir: directory where airfoils and outputs are stored.
           For example: '.\\xfoil\\output'
           By default, no dir is supplied and output will be in same dir as
           xfoil.

    :param alfas: list/array/float/int of angles of attack.

    :param output: defines the kind of output desired from xfoil.  There
           are four posssible choices (by default, Cp is chosen):

          - Cp: generates files with Pressure coefficients for
                desired alfas.
          - Dump: generates file with Velocity along surface, Delta
                  star,theta and Cf vs s,x,y for several alfas.
          - Polar: generates file with CL, CD, CM, CDp, Top_Xtr,
                   Bot_Xtr.
          - Alfa_L_0: generates a file with the value of the angle
                      of attack that lift is equal to zero.
          - Coordinates: returns the coordinates of a NACA airfoil.

    :param Reynolds: Reynolds number in case the simulation is for a
          viscous flow. In case not informed, the code will assume
          inviscid.

    :param Mach: Mach number in case the simulation has to take in
          account compressibility effects through the Prandtl-Glauert
          correlation. If not informed, the code will not use the
          correction. For logical reasons, if Mach is informed a
          Reynolds number different from zero must also be informed.

    :param  plots: the code is able to save in a .ps file all the plots
          of Cp vs.alfa. By default, this option is deactivated.

    :param NACA: Boolean variable that defines if the code imports an
          airfoil from a file or generates a NACA airfoil.

    :param GDES: XFOIL function that improves the airfoil shape in case
          the selected points do not provide a good shape. The CADD
          function is also used. For more information about these
          functions, use the XFOIL manual.

    :param iteration: changes how many times XFOIL will try to make the
          results converge. Speciallt important for viscous flows

    :param flap: determines if there is a flap. In case there is the
          expected input is [x_hinge, y_hinge, deflection(angles)].
          y_hinge is determined to be exactly in the middle between the
          upper and lower surfaces.

    :param PANE: if there are more than 495 surface points, the paneling
          method will not be used. Need to use the PANE subroutine to
          solve this. It will find the best points that represent the
          geometry (only 160 of them).

    :param NORM: For good results using the panel method, Xfoil
          requires normalized coordinates, so this option should
          always be True.

    :rtype: dictionary with outputs relevant to the specific output type.
            Usually x,y coordinates will be normalized.

    As a side note, it is much more eficient to run a single run with
    multiple angles of attack rather than multiple runs, each with a
    single angle of attack.

    Created on Sun Mar  9 14:58:25 2014

    Last update Fr Jul 13 15:38:40 2015

    @author: Pedro Leal (Based on Hakan Tiftikci's code)
    """
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #                               Functions
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def issueCmd(cmd: str, echo=echo):
        """Submit a command through PIPE to the command lineself.

        (Therefore leading the commands to xfoil.)

        @author: Hakan Tiftikci
        """
        xfoil.stdin.write(cmd + '\n')
        if echo:
            print(cmd)
            while True:
                output = nbsr.readline(0.05)
                # 0.05 secs to let the shell output the result
                if not output:
                    break
                print(output)

    def submit(output, alfa, dir=outdir):
        """Submit job to xfoil and saves file.

        Standard output file= function_airfoil_alfa.txt, where alfa has
        4 digits, where two of them are for decimals. i.e.
        cp_naca2244_0200. Analysis for Pressure Coefficients for a
        naca2244 at an angle of degrees.

        Possible to output other results such as theta, delta star
        through the choice of the ouput, but not implemented here.

        @author: Pedro Leal (Based on Hakan Tiftikci's code)
        """
        if output == "Alfa_L_0":
            issueCmd('CL 0')

        else:
            # Submit job for given angle of attack
            issueCmd(f'ALFA {alfa:4f}')

            if plots is True:
                issueCmd('HARD')
                shutil.copyfile('plot.ps',
                                f'plot_{output}_{airfoil}_{alfa}.ps')
            if output == 'Cp':
                # Creating the file with the Pressure Coefficients
                filename = file_name(airfoil, alfas, output)
                try:
                    os.remove(os.path.join(dir, filename))
                except OSError:
                    pass
                # Before writing file, denormalize it
                path_to_output = os.path.join(dir, filename)
                issueCmd(fr'CPWR {path_to_output}')
            elif output == 'Dump':
                # Creating the file with the Pressure Coefficients
                filename = file_name(airfoil, alfas, output)
                try:
                    os.remove(os.path.join(dir, filename))
                except OSError:
                    pass
                path_to_output = os.path.join(dir, filename)
                issueCmd(fr'DUMP {path_to_output}')

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #                Characteristics of the simulation
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # By default the code considers the flow to be inviscid.
    Viscid = False
    if Reynolds != 0:
        Viscid = True
    # Is alpha given or not?(in case of Alfa_L_0, then alfas=False)
    if alfas != 'none':
        # print(type(alfas))
        # Single or multiple runs?
        if type(alfas) == list or type(alfas) == np.ndarray:
            Multiple = True
        elif type(alfas) == int or type(alfas) == float or \
                type(alfas) == np.float64 or type(alfas) == np.float32:
            Multiple = False
    elif (output == "Alfa_L_0" or output == "Coordinates") and alfas == 'none':
        Multiple = False
    elif output == "Alfa_L_0" and alfas != 'none':
        raise Exception("To find alpha_L_0, alfas must not be defined")
    elif output != "Alfa_L_0" and alfas == 'none':
        raise Exception("To find anything except alpha_L_0, you need to "
                        "define the values for alfa")

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #                           Start Xfoil
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # """For communication with the xfoil through the command line the
    # Popen class from subprocess is used. stdin and stdout both
    # represent inputs and outputs with the process run on the command
    # line, in this case, xfoil.
    #
    # class Popen(args, bufsize=0, executable=None,
    #             stdin=None, stdout=None, stderr=None,
    #             preexec_fn=None, close_fds=False, shell=False,
    #             cwd=None, env=None, universal_newlines=False,
    #             startupinfo=None, creationflags=0):

    # The following keys avoid the xfoil pop-up
    # source: http://stackoverflow.com/questions/1765078/how-to-avoid-
    # console-window-with-pyw-file-containing-os-system-call
    if pf.system() == "Windows":
        startupinfo = sp.STARTUPINFO()
        startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
        xfoil_file = 'xfoil.exe'
    else:
        startupinfo = None
        xfoil_file = 'Xfoil.app/Contents/Resources/xfoil'

    # Calling xfoil with Poper
    xfoil = sp.Popen([xfoil_file],
                     stdin=sp.PIPE,
                     stdout=sp.PIPE,
                     stderr=sp.PIPE,
                     cwd=os.getcwd(),
                     startupinfo=startupinfo,
                     encoding='utf8',
                     bufsize=1)
    # wrap with NonBlockingStreamReader object
    nbsr = NonBlockingStreamReader(xfoil.stdout)
    # Turn graphics off (since we are only sending and reading text)
    issueCmd('PLOP')
    issueCmd('G')
    issueCmd('')
    # Loading geometry
    if NORM:  # Normalize airfoil
        issueCmd('NORM')
    if NACA:
        issueCmd(f'{airfoil}')
    else:
        path_to_airfoil = os.path.join(indir, airfoil)
        issueCmd(fr'load {path_to_airfoil}')
    # Once you load a set of points in xfoil you can create a name
    issueCmd(f'{airfoil}')
    if PANE:  # Adapting points for better plots
        issueCmd('PANE')
    if GDES:
        issueCmd('GDES')   # enter GDES menu
        issueCmd('CADD')   # add points at corners
        issueCmd('')       # accept default input
        issueCmd('')       # accept default input
        issueCmd('')       # accept default input
        issueCmd('')       # accept default input
        issueCmd('PANE')   # regenerate paneling
    if flap is not None:
        issueCmd('GDES')  # enter GDES menu
        issueCmd('FLAP')  # enter FLAP menu
        issueCmd(f'{flap[0]}')  # insert x location
        issueCmd(f'{flap[1]}')  # insert y location
        # insesrt deflection in degrees
        issueCmd(f'{flap[2]}')
        # set buffer airfoil as current airfoil
        issueCmd('eXec')
        issueCmd('')      # exit GDES menu  # Flap design option
    # If output equals Coordinates, no analysis will be realized, only the
    # coordinates of the shape will be outputed
    if output == 'Coordinates':
        issueCmd('SAVE')
        path_to_coord = os.path.join(outdir, output + '_' + airfoil)
        issueCmd(path_to_coord)
        # In case there is alread a file with that name, it will replace it.
        # The yes stands for YES otherwise Xfoil will do nothing with it.
        issueCmd('Y')
    else:
        issueCmd('OPER')  # Opening OPER module in Xfoil
        issueCmd(f'ITER {iteration}')  # Changing number of iterations
        if Viscid:
            issueCmd(f'v {Reynolds}')  # Defining Reynolds number
        # Defining Mach number for Prandtl-Gauber correlation
        issueCmd(f'MACH {Mach}')
        if output == 'Polar' or output == 'Alfa_L_0':
            issueCmd('PACC')  # Polar accumulation
            # All file names in this library are generated by the
            # filename functon.
            filename = file_name(airfoil, alfas, output)
            try:
                os.remove(os.path.join(outdir, filename))
            except OSError:
                pass
            # polar accumulation filename (read from output_reader function)
            path_to_output = os.path.join(outdir, filename)
            issueCmd(fr'{path_to_output}')
            issueCmd('')  # do not save a dump file
        if Multiple:  # For several angles of attack
            for alfa in alfas:
                submit(output, alfa)
        elif not Multiple:  # For only one angle of attack
            submit(output, alfas)
        issueCmd('')  # Exiting from OPER mode
    issueCmd('QUIT')  # Exiting from xfoil

    xfoil.stdin.close()
    xfoil.wait()


def create_input(x, y_u, y_l=None,
                 filename='test', different_x_upper_lower=False):
    """Create a plain file that XFOIL can read.

    XFOIL only reads file from the TE to the LE from the upper part
    first and then from the LE to the TE through the pressure surface.

    Inputs:
        - x: list of coordinates along the chord

        - y_u: list of coordinates normal to the chord for the upper
          surface. If y_l is not defined it is the y vector of the whole
          upper surface,

        - y_l: list of coordinates normal to the chord for the lower
          surface

        - file_name: label used for the file created

    Created on Thu Feb 27 2014

    @author: Pedro Leal
    """
    if different_x_upper_lower:
        y = y_u
    else:
        # XFOIL likes to read the files from the TE to the LE from the
        # upper part first and then from the LE to the TE through the
        # pressure surface
        x_upper = x
        x_under = np.delete(x_upper, -1)[::-1]
        x = np.append(x_upper, x_under)
        y_l = np.delete(y_l, -1)[::-1]
        y = np.append(y_u, y_l)
    # Creating files for xfoil processing
    with open(filename, 'w') as DataFile:
        for i in range(0, len(x)):
            DataFile.write('     %f    %f\n' % (x[i], y[i]))

    return 0


def prepare_xfoil(Coordinates_Upper, Coordinates_Lower, chord,  # noqa C901
                  reposition=False, FSI=False):
    """Prepare XFOIL airfoil file.

    The upper and lower functions will be the points in ordered
    fashion. Because of the way that XFOIL works the points start at
    the Trailing Edge on the upper surface going trough the Leading
    Edge and returning to the Trailing Edge form the bottom surface.
    """
    def Reposition(CoordinatesU, CoordinatesL):
        """Transform airfoil coordinates.

        Reposition the airfoils coordinates so that the leading
        edge is at x=y=0 and that the the trailing edge is on x=0 axis.
        """
        # Find the coordinates of the trailing edge
        LE = {'x': 0, 'y': 0}
        cx = CoordinatesU['x']
        LE['x'] = min(cx)
        index_LE = cx.index(LE['x'])
        LE['y'] = cx[index_LE]

        All_Rotated_Coordinates = {}
        count = 0
        for Coordinates in [CoordinatesU, CoordinatesL]:
            # Repositioning Leading Edge
            for key in Coordinates:
                c = Coordinates[key]
                c = [i - LE[key] for i in c]
                Coordinates[key] = c
        """ Find the coordinates of the trailing edge. Because of the
        thickness of the TE, it is necessary to find the point with
        max(x) for both surfaces and take the average between them
        to find the actual TE.
        """

        TE = {'x': 0, 'y': 0}

        cxU = CoordinatesU['x']
        cyU = CoordinatesU['y']
        TExU = max(cxU)
        index_TE = cxU.index(TExU)
        TEyU = cyU[index_TE]

        cxL = CoordinatesL['x']
        cyL = CoordinatesL['y']
        TExL = max(cxL)
        index_TE = cxL.index(TExL)
        TEyL = cyL[index_TE]

        TE['x'] = (TExU+TExL) / 2.
        TE['y'] = (TEyU+TEyL) / 2.

        # Rotating according to the position of the trailing edge
        theta = math.atan(TE['y'] / TE['x'])

        # Rotation transformation Matrix
        T = [[math.cos(theta), math.sin(theta)],
             [-math.sin(theta), math.cos(theta)]]

        for Coordinates in [CoordinatesU, CoordinatesL]:
            Rotated_Coordinates = {'x': [], 'y': []}
            for i in range(len(Coordinates['x'])):
                cx = Coordinates['x'][i]
                cy = Coordinates['y'][i]
                rot_x = T[0][0]*cx + T[0][1]*cy
                rot_y = T[1][0]*cx + T[1][1]*cy
                Rotated_Coordinates['x'].append(rot_x)
                Rotated_Coordinates['y'].append(rot_y)
            All_Rotated_Coordinates['%s' % count] = Rotated_Coordinates
            count += 1
        # If there is a great rotation, noded that are not at the trailing edge
        # can have a smaller x-coordinate. Have to rotate in relation to TE,
        # and then translate. Angle gamma
        if (min(All_Rotated_Coordinates['0']['x']) < 0
                or min(All_Rotated_Coordinates['1']['x']) < 0):
            count = 0

            cxU = All_Rotated_Coordinates['0']['x']
            cyU = All_Rotated_Coordinates['0']['y']
            TExU = max(cxU)

            cxL = All_Rotated_Coordinates['1']['x']
            cyL = All_Rotated_Coordinates['1']['y']
            TExL = max(cxL)

            x_TE = (TExU+TExL) / 2.
            print('trailing edge x', x_TE)
            for i in range(len(cxU)):
                cxU[i] = cxU[i] - x_TE
            for i in range(len(cxL)):
                cxL[i] = cxL[i] - x_TE
            # find leading edge
            # (it is the most distant node from the trailing edge)
            max_d = 0
            x_LE = 0
            y_LE = 0

            for i in range(len(cxU)):
                d_i = math.sqrt(cxU[i]**2 + cyU[i]**2)
                if d_i > max_d:
                    max_d = d_i
                    x_LE = cxU[i]
                    y_LE = cyU[i]

            for i in range(len(cxL)):
                d_i = math.sqrt(cxL[i]**2 + cyL[i]**2)
                if d_i > max_d:
                    max_d = d_i
                    x_LE = cxL[i]
                    y_LE = cyL[i]

            # Calculate rotation angle
            gamma = math.atan(y_LE/x_LE)

            # Rotation transformation Matrix
            T = [[math.cos(gamma), math.sin(gamma)],
                 [-math.sin(gamma), math.cos(gamma)]]

            # Find x-coordinate of leading edge to subtract afterwards
            rotated_x_LE = T[0][0]*x_LE + T[0][1]*y_LE + x_TE
            rotated_y_LE = T[1][0]*x_LE + T[1][1]*y_LE  # noqa W0612

            old_Rotated_Coordinates = All_Rotated_Coordinates  # noqa W0612
            for Coordinates in [{'x': cxU, 'y': cyU}, {'x': cxL, 'y': cyL}]:
                Rotated_Coordinates = {'x': [], 'y': []}
                for i in range(len(Coordinates['x'])):
                    cx = Coordinates['x'][i]
                    cy = Coordinates['y'][i]
                    rot_x = T[0][0]*cx + T[0][1]*cy
                    rot_y = T[1][0]*cx + T[1][1]*cy
                    Rotated_Coordinates['x'].append(rot_x + x_TE
                                                    - rotated_x_LE)
                    Rotated_Coordinates['y'].append(rot_y)

                All_Rotated_Coordinates['%s' % count] = Rotated_Coordinates
                count += 1
        return All_Rotated_Coordinates['0'], All_Rotated_Coordinates['1']

    upper = []
    lower = []
    print("Starting to prepare points")

    # At first we'll organize the files by its x values
    for i in range(len(Coordinates_Upper['x'])):
        # For each x value, we will check the correpondent y value so
        # that we can classify them as upper or lower
        upper.append([Coordinates_Upper['x'][i] / chord,
                      Coordinates_Upper['y'][i] / chord])

    for i in range(len(Coordinates_Lower['x'])):
        # For each x value, we will check the correpondent y value so
        # that we  can classify them as upper or lower
        lower.append([Coordinates_Lower['x'][i] / chord,
                      Coordinates_Lower['y'][i] / chord])
    print("Sorting Stuff up")

    if reposition is True:
        # Sort in a convenient way for calculating the error
        upper = sorted(upper, key=lambda coord: coord[0], reverse=False)
        lower = sorted(lower, key=lambda coord: coord[0], reverse=False)
        print('Repositioning')
        cu = {'x': [], 'y': []}
        cl = {'x': [], 'y': []}
        for i in range(len(upper)):
            cu['x'].append(upper[i][0])
            cu['y'].append(upper[i][1])
        for i in range(len(lower)):
            cl['x'].append(lower[i][0])
            cl['y'].append(lower[i][1])
        upper, lower = Reposition(cu, cl)
        print("Done preparing points")
        return upper, lower
    elif FSI is True:
        upper = sorted(upper, key=lambda coord: coord[0], reverse=False)
        lower = sorted(lower, key=lambda coord: coord[0], reverse=False)
        print("Done preparing points")
        return upper, lower
    else:
        # Sort in a way that comprehensible for xfoil and elimates the
        # repeated point at the LE
        upper = sorted(upper, key=lambda coord: coord[0], reverse=True)
        lower = sorted(lower, key=lambda coord: coord[0], reverse=False)[1:]
        Coordinates = upper + lower
        print("Done preparing points")
        return Coordinates


def output_reader(filename, dir='', separator='\t', output=None,  # noqa C901
                  rows_to_skip=0, header=0, delete=False, structure=False,
                  type_structure=None):
    """Function that opens files of any kind.

    Able to skip rows and read headers if necessary.

    Inputs:
        - filename: just the name of the file to read.

        - dir: directory where airfoils and outputs are stored.
          For example:  '.\\xfoil\\output'
          By default, no dir is supplied and output will be in same dir as
          xfoil.

        - separator: Main kind of separator in file. The code will
          replace any variants of this separator for processing. Extra
          components such as end-line, kg m are all eliminated. Separator
          can also be a list of separators to use

        - output: defines what the kind of file we are opening to
          ensure we can skip the right amount of lines. By default it
          is None so it can open any other file.

        - rows_to_skip: amount of rows to initialy skip in the file. If
          the output is different then None, for the different types of
          files it is defined as:
          - Polar files = 10
          - Dump files = 0
          - Cp files = 2
          - Coordinates = 1

        - header: The header list will act as the keys of the output
          dictionary. For the function to work, a header IS necessary.
          If not specified by the user, the function will assume that
          the header can be found in the file that it is opening.

        - delete: if True, deletes file read.

        - structure: the file that he is being read has a given structure. For
          a file with the following structure:
                0
                0 0
                0.0996174 0.00873875
                1
                0.0996174 0.00873875
                0.199258 0.0172063
          For the case where the header:
                >> header = ['element', 'x1', 'y1', 'x2', 'y2']
          A possible structure is:
                >> structure = [['element'], ['x1', 'y1'], ['x2', 'y2']]

        - type_structure: ['string', 'time', 'float', 'time', 'float']

    Output:
        - Dictionary with all the header values as keys

    Created on Thu Mar 14 2014
    @author: Pedro Leal
    """
    if header != 0:
        if type_structure is None:
            type_structure = len(header)*['float']

    def format_output(variable, type_structure):
        if type_structure is None:
            return float(variable)
        if type_structure == 'seconds':
            try:
                seconds = time.strptime(variable.split('.')[0], '%H:%M:%S')
                miliseconds = (float(variable.split('.')[1])
                               * 0.1**len(variable.split('.')[1]))
                total = (miliseconds
                         + datetime.timedelta(hours=seconds.tm_hour,
                                              minutes=seconds.tm_min,
                                              seconds=seconds.tm_sec
                                              ).total_seconds())

            except: # noqa E722
                seconds = time.strptime(variable.split('.')[0], '%M:%S')
                miliseconds = (float(variable.split('.')[1])
                               * 0.1**len(variable.split('.')[1]))
                total = (miliseconds
                         + datetime.timedelta(hours=seconds.tm_hour,
                                              minutes=seconds.tm_min,
                                              seconds=seconds.tm_sec
                                              ).total_seconds())
            return total
        elif type_structure == 'string':
            return variable
        elif type_structure == 'float':
            return float(variable)

    # In case we are using an XFOIL file, we define the number of rows
    # skipped
    if output == 'Polar' or output == 'Alfa_L_0':
        rows_to_skip = 10
    elif output == 'Dump':
        rows_to_skip = 0
    elif output == 'Cp':
        if pf.system() == 'Windows':
            rows_to_skip = 2
        else:
            rows_to_skip = 0
    elif output == 'Coordinates':
        rows_to_skip = 1
    # n is the amount of lines to skip
    Data = {}
    if header != 0:
        header_done = True
        for head in header:
            Data[head] = []
    else:
        header_done = False
    count_skip = 0

    # Add the possibility of more than one separator
    if type(separator) != list:
        separator_list = [separator]
    else:
        separator_list = separator
    structure_count = 0
    with open(os.path.join(dir, filename), "r") as myfile:
        # Jump first lines which are useless
        for line in myfile:
            if count_skip < rows_to_skip:
                count_skip += 1
                # Basically do nothing
            elif header_done is False:
                # If the user did not specify the header the code will
                # read the first line after the skipped rows as the
                # header
                if header == 0:
                    # Open line and replace anything we do not want (
                    # variants of the separator and units)
                    for separator in separator_list:
                        line = line.replace(
                            separator
                            + separator
                            + separator
                            + separator
                            + separator
                            + separator,
                            ' '
                            ).replace(
                                separator
                                + separator
                                + separator
                                + separator
                                + separator,
                                ' '
                                ).replace(
                                    separator
                                    + separator
                                    + separator
                                    + separator,
                                    ' '
                                    ).replace(
                                        separator
                                        + separator
                                        + separator,
                                        ' '
                                        ).replace(
                                            separator
                                            + separator,
                                            ' '
                                            ).replace(
                                                separator,
                                                ' '
                                                ).replace(
                                                    "\n", ""
                                                    ).replace(
                                                    "(kg)", ""
                                                    ).replace(
                                                        "(m)", ""
                                                        ).replace(
                                                            "(Pa)", ""
                                                            ).replace(
                                                                "(in)", ""
                                                                ).replace(
                                                                    "#", ""
                                                                    )
                    header = line.split(' ')
                    n_del = header.count('')
                    for n_del in range(0, n_del):
                        header.remove('')
                    for head in header:
                        Data[head] = []
                    # To avoid having two headers, we assign the False
                    # value to header which will not let it happen
                    header_done = True
                # If the user defines a list of values for the header,
                # the code reads it and creates libraries with it.
                elif type(header) == list:
                    for head in header:
                        Data[head] = []
                    header_done = True
                if type_structure is None:
                    type_structure = len(header)*['float']
            else:
                if structure is False:
                    for separator in separator_list:
                        line = line.replace(
                            separator
                            + separator
                            + separator,
                            ' '
                            ).replace(
                                separator
                                + separator,
                                ' '
                                ).replace(
                                    separator,
                                    ' '
                                    ).replace(
                                        "\n", ""
                                        ).replace(
                                            '---------', ''
                                            ).replace(
                                                '--------', ''
                                                ).replace(
                                                    '-------', ''
                                                    ).replace(
                                                        '------', ''
                                                        )

                    line_components = " -".join(line.rsplit("-", 1))
                    line_components = line_components.split(' ')
                    # line_components = line.split(' ')

                    n_del = line_components.count('')
                    for n in range(0, n_del):
                        line_components.remove('')

                    if line_components != []:
                        for j in range(0, len(header)):

                            try:
                                Data[header[j]].append(
                                    format_output(line_components[j],
                                                  type_structure[j]))
                            except:  #noqa E722
                                print('Error when recording for: ')
                                print('Line components:', line_components)
                                print('type structure:', type_structure)
                                print('index:', j)
                                print('header:', header)
                                raise ValueError('Something went wrong')
                # Use structure code
                else:
                    current_structure = structure[structure_count]

                    line = line.replace(
                        separator
                        + separator
                        + separator,
                        ' '
                        ).replace(
                            separator
                            + separator,
                            ' '
                            ).replace(
                                separator,
                                ' '
                                ).replace(
                                    "\n", ""
                                    ).replace(
                                        '---------', ''
                                        ).replace(
                                            '--------', ''
                                            ).replace(
                                                '-------', ''
                                                ).replace(
                                                    '------', ''
                                                    ).replace('-', ' -'
                                                              )

                    line_components = " -".join(line.rsplit("-", 1))
                    line_components = line_components.split(' ')
                    # line_components = line.split(' ')

                    n_del = line_components.count('')
                    for n in range(0, n_del):
                        line_components.remove('')

                    if line_components != []:
                        for j in range(0, len(line_components)):
                            Data[current_structure[j]].append(
                                format_output(line_components[j],
                                              type_structure[j]))
                        structure_count += 1
                        if structure_count == len(structure):
                            structure_count = 0
                # else DO NOTHING!
    # If delete file True, remove file from directory
    if delete:
        os.remove(os.path.join(dir, filename))
    return Data


def alfa_for_file(alfa):
    """Generate standard name for angles.

    This is mainly used by the file_name function.

    @author: Pedro Leal
    """
    alfa = '%.2f' % alfa
    inter, dec = alfa.split('.')
    inter_number = int(inter)
    inter = '%.2d' % inter_number
    if inter_number < 0:
        inter = 'n' + inter
    alfa = inter + dec
    return alfa


def file_name(airfoil, alfas='none', output='Cp'):  #noqa R701
    """Create standard name for the files generated by XFOIL.

    :param airfoil: the name of the plain file where the airfoil
           geometry is stored (variable airfoil).

    :param alfas: list/array/float/int of a single angle of attack for
          Cp and Dump, but the whole list for a Polar. Only the initial
          and the final values are used

    :param output: defines the kind of output desired from xfoil. There
           are three posssible choices:

           - Cp: generates files with Pressure coefficients for
                 desired alfas
           - Dump: generates file with Velocity along surface, Delta
                   star and theta and Cf vs s,x,y for several alfas
           - Polar: generates file with CL, CD, CM, CDp, Top_Xtr,
                    Bot_Xtr
           - Alpha_L_0: calculate the angle of attack that lift is
                        zero

    :returns: The output has the following format (by default, Cp is chosen):

        - for Cp and Dump: output_airfoil_alfa
           >>> file_name('naca2244', alfas=2.0, output='Cp')
           >>> Cp_naca2244_0200

        - for Polar: Polar_airfoil_alfa_i_alfa_f
           >>> file_name('naca2244', alfas=[-2.0, 2.0], output='Polar')
           >>> Polar_naca2244_n0200_0200

        - for Alpha_L_0: Alpha_L_0_airfoil
           >>> file_name('naca2244', output='Alpha_L_0')
           >>> Alpha_L_0_naca2244

    Created on Thu Mar 16 2014
    @author: Pedro Leal
    """
    # At first verify if alfas was defined
    if alfas == 'none':
        filename = '%s_%s' % (output, airfoil)
    elif alfas != 'none':
        if output == 'Cp' or output == 'Dump':
            if type(alfas) == list:
                alfas = alfas[0]
            alfa = alfa_for_file(alfas)

            filename = '%s_%s_%s' % (output, airfoil, alfa)

        if output == 'Polar':
            # In case it is only for one angle of attack, the same
            # angle will be repeated. This is done to keep the
            # formating
            if (type(alfas) == int or type(alfas) == float or
               type(alfas) == np.float64 or type(alfas) == np.float32):
                alfas = [alfas]
                alfa_i = alfa_for_file(alfas[0])
                alfa_f = alfa_for_file(alfas[-1])
                # Name of file with polar information
            else:
                alfa_i = alfas[0]
                alfa_f = alfas[-1]
            filename = '%s_%s_%s_%s' % (output, airfoil, alfa_i, alfa_f)
    return filename

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#                           Utility functions
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


def find_coefficients(airfoil, alpha, indir='', outdir='', Reynolds=0,  # noqa R701
                      iteration=10,
                      echo=False, NACA=True, delete=False,
                      PANE=False, GDES=False):
    """Calculate the coefficients of an airfoil.

    Includes lift, drag, moment, friction etc coefficients.
    """
    filename = file_name(airfoil, alpha, output='Polar')
    # If file already exists, there is no need to recalculate it.
    if not os.path.isfile(os.path.join(outdir, filename)):
        call(airfoil, indir=indir, outdir=outdir, alfas=alpha,
             Reynolds=Reynolds, output='Polar', iteration=iteration, echo=echo,
             NACA=NACA, PANE=PANE, GDES=GDES)

    coefficients = {}
    # Data from file
    Data = output_reader(filename, dir=outdir, output='Polar', delete=delete)
    for key in Data:
        try:
            if type(alpha) == list:
                coefficients[key] = Data[key]
                coefficients['LtoD'] = [Data['CL'][i]/Data['CD'][i]
                                        for i in range(len(Data['alpha']))]
            elif (type(alpha) == float or type(alpha) == int
                  or type(alpha) == np.float64 or type(alpha) == np.float32):
                coefficients[key] = Data[key][0]
                coefficients['LtoD'] = Data['CL'][0]/Data['CD'][0]
        except:  #noqa E722
            coefficients[key] = None
    if delete:
        os.remove(os.path.join(outdir, filename))
    return coefficients


def find_pressure_coefficients(airfoil, alpha, indir='', outdir='', Reynolds=0,
                               iteration=10, echo=False, NACA=True,
                               use_previous=False, chord=1., PANE=False,
                               GDES=False, delete=False):
    """Calculate the pressure coefficients of an airfoil."""
    filename = file_name(airfoil, alpha, output='Cp')

    # If file already exists, there is no need to recalculate it.
    if not os.path.isfile(os.path.join(outdir, filename)):
            call(airfoil, indir=indir, outdir=outdir, alfas=alpha,
                 Reynolds=Reynolds, output='Cp', iteration=iteration,
                 echo=echo, NACA=NACA, PANE=PANE, GDES=GDES)
    coefficients = {}
    # Data from file
    Data = output_reader(filename, dir=outdir, output='Cp', delete=delete)

    for key in Data:
        coefficients[key] = Data[key]
    if chord != 1.:
        for i in range(len(Data[key])):
            coefficients['x'] = coefficients['x']*chord
            coefficients['y'] = coefficients['y']*chord
    return coefficients


def find_alpha_L_0(airfoil, indir='', outdir='', Reynolds=0, iteration=10,
                   NACA=True, echo=False):
    """Find zero lift angle of attack.

    Calculate the angle of attack where the lift coefficient
    is equal to zero.
    """
    filename = file_name(airfoil, output='Alfa_L_0')
    # If file already exists, there no need to recalculate it.
    if not os.path.isfile(os.path.join(outdir, filename)):
        call(airfoil, indir=indir, outdir=outdir, output='Alfa_L_0', NACA=NACA,
             echo=echo)
    alpha = output_reader(filename, dir=outdir, output='Alfa_L_0')['alpha'][0]
    return alpha


def M_crit(airfoil, pho, speed_sound, lift, c, indir='', outdir='',
           echo=False):
    """Calculate the Critical Mach.

    This function was not validated.
    Therefore use it with caution and please improve it.

    @author: Pedro Leal
    """
    M_list = np.linspace(0.3, 0.7, 20)
    alfas = np.linspace(-15, 5, 21)
    Data_crit = {}
    Data_crit['M'] = 0
    Data_crit['CL'] = 0
    Data_crit['alpha'] = 0
    for M in M_list:
        cl = (np.sqrt(1 - M**2)/(M**2))*2*lift/pho/(speed_sound)**2/c
        call(airfoil, alfas, indir=indir, outdir=outdir, output='Polar',
             NACA=True, echo=echo)
        filename = file_name(airfoil, alfas, output='Polar')
        Data = output_reader(filename, ' ', 10, dir=outdir)
        previous_iteration = Data_crit['CL']  # noqa W0612
        for i in range(0, len(Data['CL'])):
            if Data['CL'][i] >= cl and M > Data_crit['M']:
                print(M)
                Data_crit['M'] = M
                Data_crit['CL'] = Data['CL'][i]
                Data_crit['alpha'] = Data['alpha'][i]
        # if Data_crit['CL']==previous_iteration:
    return Data_crit
