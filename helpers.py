class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def red_text(text):
    return bcolors.RED + str(text) + bcolors.ENDC


def green_text(text):
    return bcolors.OKGREEN + str(text) + bcolors.ENDC
