"""Entry point for the BadUSB heuristic detector."""

import tkinter as tk

from app import BadUSBDetectorGUI


def main() -> None:
    root = tk.Tk()
    BadUSBDetectorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
