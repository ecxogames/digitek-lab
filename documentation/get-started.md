# Getting Started with ESD Suite

Welcome to the Ecxo Softwares Development (ESD) Suite! This framework is a cross-platform desktop application engine that bridges C++, Python, and JavaScript.

## Architecture Overview

The application is built on three core pillars:
1. **C++ (Engine Layer):** Handles native system interactions, window creation, and embeds both the webview and the Python runtime.
2. **Python (Backend Layer):** Serves as the application's backend logic, scripting engine, and AI integration point.
3. **JavaScript/HTML/CSS (Frontend Layer):** Powers the user interface, rendering inside the embedded webview.

## Directory Structure

* `/engine/` - Core C++ runtime code (Entry point, window creation, webview integration).
* `/server/` - Python backend logic. Treated as private during compilation.
* `/ui/` - User interface code (HTML/CSS/JS entry points).
* `/public/` - Shared assets accessible by all layers.
* `/private/` - Restricted code (C++, JS, Python) accessible only via secure imports.
* `/scripts/` - Utility scripts for development and building.

## Build Requirements

To build the prototype, you need:
- CMake (3.14+)
- A C++ Compiler (MSVC on Windows, Clang/GCC on macOS/Linux)
- Python 3 (installed on the system with development headers/libs)

## Setting Up the Prototype

### 1. Run Setup
You have to install all the dependencies, but don't worry, the [`setup.py`](/scripts/setup.py) script does everything for you:
```bash
python scripts/setup.py
```

### 2. Build 
To compile the C++ engine layer, run the [`build.py`](/scripts/build.py) script:
```bash
python scripts/build.py
```

### 3. Run the Application
Start testing the program by running the [`dev.py`](/scripts/dev.py) script, which will launch the application in development mode:
```bash
python scripts/dev.py
```

## Next Steps
Now you are ready to start developing your very own software using the ESD Suite! The application will launch with a simple UI, and you can begin customizing the frontend and backend logic as needed.

For more detailed documentation on how to use the API, integrate AI features, and customize the UI, please refer to the [API Documentation](api-docs.md) in the `documentation` folder of this project or visit the [ESD Engine's Website](https://esde.ecxogames.ca/).