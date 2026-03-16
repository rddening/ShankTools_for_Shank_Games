pyinstaller --onefile --name ShankTools_alpha_version --hidden-import=main_tools.ktex --hidden-import=concurrent --hidden-import=concurrent.futures --hidden-import=concurrent.futures._base --hidden-import=concurrent.futures.thread --hidden-import=concurrent.futures.process --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --noconsole --icon horror.ico main.py

with console

pyinstaller --onefile --name ShankTools_alpha_version --hidden-import=main_tools.ktex --hidden-import=concurrent --hidden-import=concurrent.futures --hidden-import=concurrent.futures._base --hidden-import=concurrent.futures.thread --hidden-import=concurrent.futures.process --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageTk --icon horror.ico main.py