# plugins/Test_ShankTools Viewer.py

def register(app): # this register function so the STV (ShankTools Viewer) defines it as a plugin
    
    from tkinter import messagebox

    def my_action():
        messagebox.showinfo("info", "Hello\n\nthis is my STV aka ShankTools Viewer!\nthis app will be new face of ShankTools and the most big project\n\nthis project will have new stuff such as viewer animation and add new animation by using the same assets of the character (hand, legs, etc...)\n\nand all tools that have been working on will be port to this app (not all of them the rest of them will coming soon)\n\nand this app still in the early alpha version (to be more ) and it will take time and effort. in meantime see you guy's later :)")
        
    import tkinter as tk
    btn = tk.Button(
        app.sidebar,
        text="info about this STV",
        command=my_action
    )
    btn.pack(pady=5, padx=10, fill="x")