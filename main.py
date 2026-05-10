"""
FixKar — Main Entry Point
=========================
Initialises the DB, starts Tkinter, and manages navigation
between all screens: Home → Fault → Status → Rating → Home.
"""

import tkinter as tk
from tkinter import messagebox
import sys, os

# Make sure imports resolve from the project root
sys.path.insert(0, os.path.dirname(__file__))

from db.setup import init_db
from ui.fault_screen    import FaultScreen
from ui.status_screen   import StatusScreen
from ui.rating_screen   import RatingScreen
from ui.mechanic_dash   import MechanicDashboard

BG     = "#0f1117"
SURFACE= "#1a1d27"
ACCENT = "#e63946"
TEXT   = "#eaeaea"
MUTED  = "#8b8fa8"
FONT_B = ("Courier New", 11, "bold")
FONT_H = ("Courier New", 22, "bold")
FONT_SM= ("Courier New", 9)


class FixKarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FixKar — Vehicle Rescue System")
        self.geometry("820x640")
        self.configure(bg=BG)
        self.resizable(True, True)
        self._current_frame = None
        self.show_home()

    # ── Navigation helpers ────────────────────────────────

    def _clear(self):
        if self._current_frame:
            self._current_frame.destroy()
            self._current_frame = None

    def _show(self, frame):
        self._clear()
        self._current_frame = frame
        frame.pack(fill="both", expand=True)

    # ── Screens ───────────────────────────────────────────

    def show_home(self):
        self._clear()
        frame = tk.Frame(self, bg=BG)
        self._current_frame = frame
        frame.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(frame, bg=SURFACE, pady=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  FIXKAR", font=("Courier New", 36, "bold"),
                 bg=SURFACE, fg=ACCENT).pack()
        tk.Label(hdr, text="Intelligent On-Demand Vehicle Rescue & Mechanic Dispatch",
                 font=FONT_SM, bg=SURFACE, fg=MUTED).pack(pady=(4,0))

        # Centre card
        card = tk.Frame(frame, bg="#1a1d27", padx=50, pady=40)
        card.pack(expand=True)

        tk.Label(card, text="SELECT AN OPTION", font=FONT_B,
                 bg="#1a1d27", fg=MUTED).pack(pady=(0,20))

        buttons = [
            ("🔧   Report a Fault",       ACCENT,   "#c0392b", self.show_fault),
            ("📋   Mechanic Dashboard",   "#2c3e50", "#34495e", self.show_dashboard),
            ("ℹ️   About FixKar",          "#1a1d27", "#2c3e50", self.show_about),
        ]
        for text, bg, hover, cmd in buttons:
            btn = tk.Button(
                card, text=text,
                font=("Courier New", 13, "bold"),
                bg=bg, fg=TEXT, relief="flat",
                activebackground=hover, activeforeground=TEXT,
                cursor="hand2", pady=14, width=30,
                command=cmd
            )
            btn.pack(pady=6, fill="x")

        # Footer
        tk.Label(frame,
                 text="Bahria University · Software Design Architecture · BSE-4B",
                 font=FONT_SM, bg=BG, fg=MUTED).pack(side="bottom", pady=10)

    def show_fault(self):
        screen = FaultScreen(self, on_job_submitted=self._on_job_submitted)
        self._show(screen)

    def _on_job_submitted(self, job_id, mechanic):
        self.show_status(job_id, mechanic)

    def show_status(self, job_id, mechanic):
        screen = StatusScreen(
            self, job_id, mechanic,
            on_completed=self._on_job_completed
        )
        self._show(screen)

    def _on_job_completed(self, job_id, mechanic_id):
        self.show_rating(job_id, mechanic_id)

    def show_rating(self, job_id, mechanic_id):
        screen = RatingScreen(
            self, job_id, mechanic_id,
            on_done=self.show_home
        )
        self._show(screen)

    def show_dashboard(self):
        screen = MechanicDashboard(self, on_back=self.show_home)
        self._show(screen)

    def show_about(self):
        messagebox.showinfo(
            "About FixKar",
            "FixKar — Intelligent Vehicle Rescue System\n\n"
            "Built with Python 3.10+ · Tkinter · SQLite\n\n"
            "Design Patterns Used:\n"
            "  • Factory   — Job report creation\n"
            "  • Strategy  — Mechanic dispatch (2 modes)\n"
            "  • Observer  — Auto-cascade notifications\n"
            "  • Singleton — Global rating manager\n\n"
            "Group Members:\n"
            "  Rayyan Mughal (TL) · Amanullah · Maaz Uddin\n\n"
            "Bahria University, Karachi Campus\n"
            "Course: Software Design Architecture — SEL-221"
        )


# ── Entry point ───────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app = FixKarApp()
    app.mainloop()
