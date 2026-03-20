import os
import glob
import sys
import subprocess
import time
from multiprocessing import Pool

SUCCEEDED = "\033[32msucceeded\033[0m"
FAILED = "\033[31mfailed\033[0m"
SKIPPED = "\033[35mskipped\033[0m"
WARNING = "\033[33mwarnings\033[0m "

build_format = '| {:25} | {:35} | {:18} | {:6} |'
build_separator = '-' * 88

default_boards = [
    'cluenrf52840',
    'cplaynrf52840',
    'feather52832',
    'feather52840',
    'feather52840sense',
    'itsybitsy52840',
    # Seeed boards may need work:
    'wio_tracker_1110',
    'tracker_t1000_e_lorawan',
    'xiaonRF52840',
    'xiaonRF52840Sense',
    'xiaonRF52840Plus',
    'xiaonRF52840SensePlus',
]
build_boards = []


def get_sd(name: str) -> str:
    """Return the appropriate SoftDevice menu value for a board name."""
    if '52832' in name:
        return 's132v6'
    elif '52833' in name or name == 'pca10100':
        return 's140v7'
    else:
        # Most of the boards are nRF52840
        return 's140v6'


def get_fqbn(variant: str) -> str:
    """
    Build the fully qualified board name (FQBN) for arduino-cli.

    All boards are assumed to be in the Seeeduino:nrf52 package after merging
    boards.txt, with special menu options for Seeed tracker boards.
    """
    sd = get_sd(variant)

    if variant == 'wio_tracker_1110':
        # Uses additional menus: debug_output, usb_cdc, power_supply_grove, lbm_custom
        return (
            "Seeeduino:nrf52:{}:"
            "softdevice={},debug_output={},usb_cdc={},power_supply_grove={},lbm_custom={}"
        ).format(variant, sd, 'serial', 'enable', 'on', 'sensecap')

    if variant == 'tracker_t1000_e_lorawan':
        # Uses additional menus: debug_output, usb_cdc
        return (
            "Seeeduino:nrf52:{}:"
            "softdevice={},debug_output={},usb_cdc={}"
        ).format(variant, sd, 'serial', 'enable')

    # Generic case: all other boards just use the debug level menu
    return "Seeeduino:nrf52:{}:softdevice={},debug=l0".format(variant, sd)


def get_examples_for_board(variant: str):
    """
    Select example sketches for a given board.

    - Tracker boards get their dedicated example trees.
    - All other boards build all library examples except TinyUSB (which has its own CI).

    """
    if variant == 'wio_tracker_1110':
        all_examples = list(
            glob.iglob('libraries/Wio_Tracker_1110_Examples/**/*.ino', recursive=True)
        )
    elif variant == 'tracker_t1000_e_lorawan':
        all_examples = list(
            glob.iglob('Tracker_T1000_E_LoRaWAN_Examples/**/*.ino', recursive=True)
        )
    else:
        all_examples = list(glob.iglob('libraries/**/*.ino', recursive=True))
        # Exclude TinyUSB examples (built in their own CI)
        all_examples = [i for i in all_examples if "Adafruit_TinyUSB_Arduino" not in i]

    all_examples.sort()
    return all_examples


def build_a_example(arg):
    variant = arg[0]
    sketch = arg[1]

    fqbn = get_fqbn(variant)

    # succeeded, failed, skipped
    ret = [0, 0, 0]

    start_time = time.monotonic()

    # Skip logic based on marker files in the sketch directory
    sketchdir = os.path.dirname(sketch)
    if os.path.exists(sketchdir + '/.all.test.skip') or os.path.exists(
        sketchdir + '/.' + variant + '.test.skip'
    ):
        success = SKIPPED
        ret[2] = 1
        build_result = None
    elif glob.glob(sketchdir + "/.*.test.only") and not os.path.exists(
        sketchdir + '/.' + variant + '.test.only'
    ):
        success = SKIPPED
        ret[2] = 1
        build_result = None
    else:
        build_result = subprocess.run(
            "arduino-cli compile --warnings all --fqbn {} {}".format(fqbn, sketch),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if build_result.returncode != 0:
            ret[1] = 1
            success = FAILED
        else:
            ret[0] = 1
            if build_result.stderr:
                success = WARNING
            else:
                success = SUCCEEDED

    build_duration = time.monotonic() - start_time
    print(
        build_format.format(
            sketch.split(os.path.sep)[1],
            os.path.basename(sketch),
            success,
            '{:5.2f}s'.format(build_duration),
        )
    )

    if success != SKIPPED and build_result is not None:
        # Build failed
        if build_result.returncode != 0:
            print(build_result.stdout.decode("utf-8"))

        # Build with warnings
        if build_result.stderr:
            print("::group::warning-message")
            print(build_result.stderr.decode("utf-8"))
            print("::endgroup::")

    return ret


def build_all_examples(variant: str):
    print('\n')
    print(build_separator)
    print('| {:^84} |'.format('Board ' + variant))
    print(build_separator)
    print(build_format.format('Library', 'Example', '\033[39mResult\033[0m', 'Time'))
    print(build_separator)

    all_examples = get_examples_for_board(variant)

    args = [[variant, s] for s in all_examples]
    if not args:
        # No examples found for this board, treat as skipped
        return [0, 0, 0]

    with Pool() as pool:
        result = pool.map(build_a_example, args)
        # sum all elements of same index (column sum)
        return list(map(sum, list(zip(*result))))


if __name__ == "__main__":
    # Build all default variants if no input provided
    if len(sys.argv) > 1:
        build_boards.append(sys.argv[1])
    else:
        build_boards = default_boards

    build_time = time.monotonic()

    # succeeded, failed, skipped
    total_result = [0, 0, 0]

    for board in build_boards:
        fret = build_all_examples(board)
        if len(fret) == len(total_result):
            total_result = [total_result[i] + fret[i] for i in range(len(fret))]

    build_time = time.monotonic() - build_time

    print(build_separator)
    print(
        "Build Summary: {} {}, {} {}, {} {} and took {:.2f}s".format(
            total_result[0],
            SUCCEEDED,
            total_result[1],
            FAILED,
            total_result[2],
            SKIPPED,
            build_time,
        )
    )
    print(build_separator)

    # Exit with the number of failures (0 == success)
    sys.exit(total_result[1])