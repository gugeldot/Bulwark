"""Entry point for the BadUSB heuristic detector."""

import faulthandler
import tkinter as tk

faulthandler.enable()  # print native C backtrace on SIGSEGV / SIGABRT

from app import BadUSBDetectorGUI


def main() -> None:
    root = tk.Tk()
    BadUSBDetectorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
