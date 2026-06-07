#define _CRT_SECURE_NO_WARNINGS
#include <iostream>
#include <string>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <sstream>
#include <unordered_map>

// Workaround to prevent MSVC from searching for the Python debug library (pythonXX_d.lib)
#if defined(_MSC_VER) && defined(_DEBUG)
    #undef _DEBUG
    #include <Python.h>
    #define _DEBUG
#else
    #include <Python.h>
#endif

#include "webview.h"

#ifdef ESD_EMBED_HTML
#include "embedded_html.h"
static std::string GetPageHtml(const std::string& path) {
    const auto& map = GetEmbeddedHtml();
    auto it = map.find(path);
    return (it != map.end()) ? it->second : std::string();
}
#endif

#ifdef _WIN32
#include <direct.h>
#define GetCurrentDir _getcwd
#include <windows.h>
#include <dwmapi.h>
#include <shellapi.h>
#ifndef DWMWA_CAPTION_COLOR
#define DWMWA_CAPTION_COLOR 35
#endif
#else
#include <unistd.h>
#define GetCurrentDir getcwd
#endif

// ── Modal parsing helpers ──────────────────────────────────────────────────

// Extract a quoted attribute value from an HTML-like opening tag string.
static std::string ModalAttr(const std::string& tag, const std::string& attr,
                              const std::string& def = "") {
    for (char q : {'"', '\''}) {
        std::string key = attr + "=";
        key += q;
        auto pos = tag.find(key);
        if (pos == std::string::npos) continue;
        pos += key.size();
        auto end = tag.find(q, pos);
        if (end == std::string::npos) continue;
        return tag.substr(pos, end - pos);
    }
    return def;
}

// Extract the first opening tag (e.g. "<modal ...>") for a given tag name.
static std::string ModalOpenTag(const std::string& html, const std::string& tag) {
    auto start = html.find("<" + tag);
    if (start == std::string::npos) return "";
    auto end = html.find('>', start);
    if (end == std::string::npos) return "";
    return html.substr(start, end - start + 1);
}

// Extract the trimmed inner content between <tag ...> and </tag>.
static std::string ModalInner(const std::string& html, const std::string& tag) {
    auto open = html.find("<" + tag);
    if (open == std::string::npos) return "";
    auto bodyStart = html.find('>', open);
    if (bodyStart == std::string::npos) return "";
    bodyStart++;
    auto close = html.find("</" + tag + ">", bodyStart);
    if (close == std::string::npos) return "";
    std::string inner = html.substr(bodyStart, close - bodyStart);
    auto s = inner.find_first_not_of(" \t\r\n");
    if (s == std::string::npos) return "";
    auto e = inner.find_last_not_of(" \t\r\n");
    return inner.substr(s, e - s + 1);
}

// ── Modal OS-window thread ─────────────────────────────────────────────────

struct ModalThreadParams {
    std::string generatedHtml;
    std::string windowTitle;
    int   width;
    int   height;
    int   cornerRadius;  // rounded corners applied to frameless windows (0 = none)
    bool  useOsChrome;   // true = native OS titlebar; false = WS_POPUP (frameless)
    bool  closeable;
    bool  fullscreen;    // cover the whole monitor (overlay mode)
    bool  transparent;   // transparent background so the desktop shows through
    bool  devTools;
    webview::webview* parentWv;
};

static DWORD WINAPI ModalWindowThread(LPVOID param) {
    auto* p = static_cast<ModalThreadParams*>(param);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    std::string result = "null";

    {
        webview::webview modal(p->devTools, nullptr);
        HWND mhwnd = static_cast<HWND>(modal.window());

#ifdef _WIN32
        if (!p->useOsChrome) {
            // Frameless popup — strip all OS window chrome
            LONG_PTR style = GetWindowLongPtr(mhwnd, GWL_STYLE);
            style = (style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX))
                  | WS_POPUP | WS_VISIBLE;
            SetWindowLongPtr(mhwnd, GWL_STYLE, style);
            SetWindowPos(mhwnd, nullptr, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
        } else {
            // Native titlebar — keep chrome but lock size and set title
            modal.set_title(p->windowTitle);
            if (!p->closeable) {
                HMENU hMenu = GetSystemMenu(mhwnd, FALSE);
                if (hMenu)
                    EnableMenuItem(hMenu, SC_CLOSE,
                                   MF_BYCOMMAND | MF_DISABLED | MF_GRAYED);
            }
        }

        // Overlay mode: float above other windows; a layered host window lets
        // WebView2 transparency reveal the desktop behind transparent regions.
        if (p->fullscreen || p->transparent) {
            LONG_PTR ex = GetWindowLongPtr(mhwnd, GWL_EXSTYLE);
            ex |= WS_EX_TOPMOST;
            if (p->transparent) ex |= WS_EX_LAYERED;
            SetWindowLongPtr(mhwnd, GWL_EXSTYLE, ex);
        }

        // Inherit app icon
        HICON hIcon = LoadIcon(GetModuleHandle(nullptr), MAKEINTRESOURCE(101));
        if (hIcon) {
            SendMessage(mhwnd, WM_SETICON, ICON_BIG,   (LPARAM)hIcon);
            SendMessage(mhwnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
        }
#endif
#ifdef _WIN32
        if (p->fullscreen) {
            // Overlay mode: cover the whole monitor (no centering, no rounding).
            HMONITOR hMon = MonitorFromWindow(mhwnd, MONITOR_DEFAULTTOPRIMARY);
            MONITORINFO mi = { sizeof(mi) };
            if (GetMonitorInfo(hMon, &mi)) {
                SetWindowPos(mhwnd, HWND_TOPMOST,
                             mi.rcMonitor.left, mi.rcMonitor.top,
                             mi.rcMonitor.right  - mi.rcMonitor.left,
                             mi.rcMonitor.bottom - mi.rcMonitor.top,
                             SWP_SHOWWINDOW);
            }
        } else {
#endif
            // Set size (handles DPI scaling internally)
            modal.set_size(p->width, p->height, WEBVIEW_HINT_FIXED);
#ifdef _WIN32
            // Center on nearest monitor
            {
                RECT wr;
                GetWindowRect(mhwnd, &wr);
                int aw = wr.right - wr.left;
                int ah = wr.bottom - wr.top;
                HMONITOR hMon = MonitorFromWindow(mhwnd, MONITOR_DEFAULTTONEAREST);
                MONITORINFO mi = { sizeof(mi) };
                if (GetMonitorInfo(hMon, &mi)) {
                    int x = mi.rcWork.left + (mi.rcWork.right  - mi.rcWork.left - aw) / 2;
                    int y = mi.rcWork.top  + (mi.rcWork.bottom - mi.rcWork.top  - ah) / 2;
                    SetWindowPos(mhwnd, HWND_TOP, x, y, 0, 0,
                                 SWP_NOSIZE | SWP_SHOWWINDOW);
                }
            }

            // Apply rounded corners to frameless windows
            if (!p->useOsChrome && p->cornerRadius > 0) {
                RECT wr;
                GetWindowRect(mhwnd, &wr);
                int aw = wr.right - wr.left;
                int ah = wr.bottom - wr.top;
                int r  = p->cornerRadius;
                HRGN hRgn = CreateRoundRectRgn(0, 0, aw, ah, r, r);
                SetWindowRgn(mhwnd, hRgn, TRUE);
            }
        }

        // Enable WebView2 transparency once the controller exists (post-construction).
        if (p->transparent) {
            modal.set_transparent();
        }
#endif

        // _modalClose: called by closeModal() inside the modal HTML
        modal.bind("_modalClose", [&result, &modal](std::string req) -> std::string {
            // req arrives as a JSON array e.g. [true] or ["hello"] or [null]
            std::string val = req;
            if (val.size() >= 2 && val.front() == '[' && val.back() == ']')
                val = val.substr(1, val.size() - 2);
            if (val.empty()) val = "null";
            result = val;
            modal.terminate();
            return "";
        });

        // dragWindow: lets custom titlebars initiate native window drag
        modal.bind("dragWindow", [mhwnd](std::string) -> std::string {
#ifdef _WIN32
            if (mhwnd) { ReleaseCapture(); SendMessage(mhwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0); }
#endif
            return "";
        });

        modal.set_html(p->generatedHtml);
        modal.run();
    }

    // Resolve the parent window's Promise with the modal's return value
    std::string resolvedValue   = result;
    webview::webview* parentWv  = p->parentWv;
    parentWv->dispatch([parentWv, resolvedValue]() {
        parentWv->eval("window.__esd_resolveModal(" + resolvedValue + ")");
    });

    delete p;
    CoUninitialize();
    return 0;
}

// Helper to get current directory and resolve project root
std::string GetCurrentWorkingDir() {
    char buff[FILENAME_MAX];
    GetCurrentDir(buff, FILENAME_MAX);
    std::string cwd(buff);
    
    // If run from within the build directory, strip it to reach the project root.
    size_t buildPos = cwd.find("\\build");
    if (buildPos == std::string::npos) buildPos = cwd.find("/build");
    if (buildPos != std::string::npos) {
        cwd = cwd.substr(0, buildPos);
    }
    return cwd;
}

// Helper to load properties.config
std::unordered_map<std::string, std::string> LoadConfig(const std::string& filename) {
    std::unordered_map<std::string, std::string> config;
    std::ifstream file(filename);
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') continue;
        // Trim carriage return if present (Windows CRLF issue)
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        auto delimiterPos = line.find('=');
        if (delimiterPos != std::string::npos) {
            std::string key = line.substr(0, delimiterPos);
            std::string value = line.substr(delimiterPos + 1);
            config[key] = value;
        }
    }
    return config;
}

#ifdef _WIN32
// Tell MSVC linker to build a Windows GUI app (no console by default) but keep main() as the entrypoint.
#pragma comment(linker, "/SUBSYSTEM:windows /ENTRY:mainCRTStartup")
#endif

// Function to route a string payload to Python's /server/api.py
std::string CallPythonBackend(const std::string& message) {
    std::string resultStr = "{\"error\": \"Failed to call Python\"}";
    
    // Import the API module
    PyObject* pName = PyUnicode_DecodeFSDefault("server.api");
    PyObject* pModule = PyImport_Import(pName);
    Py_DECREF(pName);

    if (pModule != nullptr) {
        PyObject* pFunc = PyObject_GetAttrString(pModule, "handle_message");
        if (pFunc && PyCallable_Check(pFunc)) {
            // Pass the string argument
            PyObject* pArgs = PyTuple_New(1);
            PyTuple_SetItem(pArgs, 0, PyUnicode_FromString(message.c_str()));
            
            PyObject* pValue = PyObject_CallObject(pFunc, pArgs);
            Py_DECREF(pArgs);
            if (pValue != nullptr) {
                resultStr = PyUnicode_AsUTF8(pValue);
                Py_DECREF(pValue);
            }
        } else {
            if (PyErr_Occurred()) PyErr_Print();
        }
        Py_XDECREF(pFunc);
        Py_DECREF(pModule);
    } else {
        if (PyErr_Occurred()) PyErr_Print();
    }
    return resultStr;
}

// Applies window properties dynamically to the window handle
void ApplyWindowProperties(webview::webview& w, HWND hwnd, const std::unordered_map<std::string, std::string>& config, bool& dragBackgroundOut) {
    std::string title = config.count("TITLE") ? config.at("TITLE") : "ESD Suite Framework";
    w.set_title(title);

    int windowWidth = 800;
    if (config.count("WINDOW_WIDTH")) {
        try { windowWidth = std::stoi(config.at("WINDOW_WIDTH")); } catch(...) {}
    }
    
    int windowHeight = 600;
    if (config.count("WINDOW_HEIGHT")) {
        try { windowHeight = std::stoi(config.at("WINDOW_HEIGHT")); } catch(...) {}
    }
    
    w.set_size(windowWidth, windowHeight, WEBVIEW_HINT_NONE);
    dragBackgroundOut = (config.count("DRAG_BACKGROUND") && config.at("DRAG_BACKGROUND") == "true");

#ifdef _WIN32
    if (!hwnd) return;

    bool canClose = (config.count("CAN_CLOSE") == 0 || config.at("CAN_CLOSE") != "false");
    bool canMinimize = (config.count("CAN_MINIMIZE") == 0 || config.at("CAN_MINIMIZE") != "false");
    bool canMaximize = (config.count("CAN_MAXIMIZE") == 0 || config.at("CAN_MAXIMIZE") != "false");
    bool showTitlebar = (config.count("TITLEBAR") == 0 || config.at("TITLEBAR") != "false");
    
    int cornerRadius = 0;
    if (config.count("CORNER_RADIUS")) {
        try { cornerRadius = std::stoi(config.at("CORNER_RADIUS")); } catch(...) {}
    }

    std::string iconPath = config.count("ICON") ? config.at("ICON") : "";
    if (!iconPath.empty()) {
        HICON hIcon = (HICON)LoadImageA(NULL, iconPath.c_str(), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
        if (hIcon) {
            SendMessage(hwnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);
            SendMessage(hwnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
        }
    }

    // Apply window styles based on properties
    LONG_PTR style = GetWindowLongPtr(hwnd, GWL_STYLE);
    if (!canMinimize) style &= ~WS_MINIMIZEBOX; else style |= WS_MINIMIZEBOX;
    if (!canMaximize) style &= ~WS_MAXIMIZEBOX; else style |= WS_MAXIMIZEBOX;
    if (!showTitlebar) {
        style &= ~(WS_CAPTION | WS_THICKFRAME);
    } else {
        style |= (WS_CAPTION | WS_THICKFRAME);
    }
    SetWindowLongPtr(hwnd, GWL_STYLE, style);
    
    // Center the window on the screen and force it to redraw its frame
    HMONITOR hMonitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi = { sizeof(mi) };
    if (GetMonitorInfo(hMonitor, &mi)) {
        int screenWidth = mi.rcWork.right - mi.rcWork.left;
        int screenHeight = mi.rcWork.bottom - mi.rcWork.top;
        int x = mi.rcWork.left + (screenWidth - windowWidth) / 2;
        int y = mi.rcWork.top + (screenHeight - windowHeight) / 2;
        SetWindowPos(hwnd, NULL, x, y, windowWidth, windowHeight, SWP_NOZORDER | SWP_FRAMECHANGED);
    } else {
        SetWindowPos(hwnd, NULL, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
    }

    if (!showTitlebar && cornerRadius > 0) {
        RECT rect;
        GetWindowRect(hwnd, &rect);
        int width = rect.right - rect.left;
        int height = rect.bottom - rect.top;
        HRGN hRgn = CreateRoundRectRgn(0, 0, width, height, cornerRadius, cornerRadius);
        SetWindowRgn(hwnd, hRgn, TRUE);
    } else {
        SetWindowRgn(hwnd, NULL, TRUE); // Ensure region is reset if not rounded
    }

    HMENU hMenu = GetSystemMenu(hwnd, FALSE);
    if (!canClose) {
        EnableMenuItem(hMenu, SC_CLOSE, MF_BYCOMMAND | MF_DISABLED | MF_GRAYED);
    } else {
        EnableMenuItem(hMenu, SC_CLOSE, MF_BYCOMMAND | MF_ENABLED);
    }
#endif
}

#ifdef _WIN32
// Switches the window to borderless fullscreen covering the entire primary monitor.
void ApplyFullscreen(webview::webview& w, HWND hwnd) {
    if (!hwnd) return;
    int screenWidth  = GetSystemMetrics(SM_CXSCREEN);
    int screenHeight = GetSystemMetrics(SM_CYSCREEN);
    // WS_VISIBLE must be kept — dropping it hides the native window while leaving
    // the WebView2 child surfaces visible, producing the staircase-white artifact.
    SetWindowLongPtr(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
    // Clear any rounded-corner clipping region before covering the full screen.
    SetWindowRgn(hwnd, NULL, FALSE);
    SetWindowPos(hwnd, HWND_TOP, 0, 0, screenWidth, screenHeight,
                 SWP_FRAMECHANGED | SWP_NOOWNERZORDER);
    w.set_size(screenWidth, screenHeight, WEBVIEW_HINT_FIXED);
}
#endif

int main() {
    std::string cwd = GetCurrentWorkingDir();
    auto rootConfig = LoadConfig(cwd + "/properties.config");
    bool isFullscreen = (rootConfig.count("FULLSCREEN") && rootConfig.at("FULLSCREEN") == "true");
    
    // Check if terminal should be hidden
    bool hideTerminal = (rootConfig.count("SHOW_TERMINAL") && rootConfig["SHOW_TERMINAL"] == "false");
#ifdef _WIN32
    if (!hideTerminal) {
        // Allocate a new console window manually since we are running as a GUI application
        AllocConsole();
        FILE* fp;
        freopen_s(&fp, "CONOUT$", "w", stdout);
        freopen_s(&fp, "CONOUT$", "w", stderr);
        freopen_s(&fp, "CONIN$", "r", stdin);
    }
#endif

    // Determine the main page
    std::string mainPageFile = rootConfig.count("MAIN_PAGE") ? rootConfig["MAIN_PAGE"] : "ui/pages/index.html";
    std::string titlebarColor = rootConfig.count("TITLEBAR_COLOR") ? rootConfig["TITLEBAR_COLOR"] : "";

    // Replace backslashes with forward slashes for URI formatting
    std::string cwdUri = cwd;
    for(size_t i = 0; i < cwdUri.length(); ++i) {
        if(cwdUri[i] == '\\') cwdUri[i] = '/';
    }

    // 1. Initialize Python Interpreter
    Py_Initialize();
    // Build a forward-slash version of cwd safe to embed in a Python string literal
    std::string pyCwd = cwd;
    for (char& c : pyCwd) { if (c == '\\') c = '/'; }

    PyRun_SimpleString(("import sys\nsys.path.insert(0, '" + pyCwd + "')\nprint('Python backend initialized.')").c_str());

    // Start local file server on port 2024 to serve project files to the webview.
    // Uses the C++ computed project root so it works correctly from any working directory.
    // Runs as a daemon thread so it exits automatically when the main process exits.
    {
        std::string serverScript =
            "import threading, http.server, socket, time\n"
            "class _ESDHandler(http.server.SimpleHTTPRequestHandler):\n"
            "    def __init__(self, *a, **kw):\n"
            "        super().__init__(*a, directory='" + pyCwd + "', **kw)\n"
            "    def end_headers(self):\n"
            "        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')\n"
            "        self.send_header('Pragma', 'no-cache')\n"
            "        self.send_header('Expires', '0')\n"
            "        super().end_headers()\n"
            "    def log_message(self, fmt, *a): pass\n"
            "def _run_server():\n"
            "    try:\n"
            "        srv = http.server.HTTPServer(('127.0.0.1', 2024), _ESDHandler)\n"
            "        srv.serve_forever()\n"
            "    except OSError:\n"
            "        pass\n"
            "threading.Thread(target=_run_server, daemon=True).start()\n"
            "# Block until port is accepting connections (max ~5 s)\n"
            "for _ in range(50):\n"
            "    try:\n"
            "        _c = socket.create_connection(('127.0.0.1', 2024), timeout=0.1)\n"
            "        _c.close(); break\n"
            "    except OSError:\n"
            "        time.sleep(0.1)\n";
        PyRun_SimpleString(serverScript.c_str());
    }

#ifdef _WIN32
    // Disable WebView2's persistent disk cache so every launch always loads fresh files.
    _putenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-allow-origins=* --disable-cache --disable-application-cache");
#endif

    // 2. Initialize the Webview
    bool devTools = true;
    if (rootConfig.count("DEVTOOLS") && rootConfig.at("DEVTOOLS") == "false") {
        devTools = false;
    }

    webview::webview w(devTools, nullptr);
    
    bool contextMenu = true;
    if (rootConfig.count("DEFAULT_CONTEXTUAL_MENU") && rootConfig.at("DEFAULT_CONTEXTUAL_MENU") == "false") {
        contextMenu = false;
    }
    
    if (!contextMenu) {
        w.init("window.addEventListener('contextmenu', e => e.preventDefault());");
    }

    HWND hwnd = nullptr;
#ifdef _WIN32
    hwnd = (HWND)w.window();
    
    // Load embedded icon and set it for the window taskbar/titlebar
    HICON hIcon = LoadIcon(GetModuleHandle(NULL), MAKEINTRESOURCE(101));
    if (hIcon) {
        SendMessage(hwnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);
        SendMessage(hwnd, WM_SETICON, ICON_SMALL, (LPARAM)hIcon);
    }
#endif

    bool dragBackground = false;

    // Optional: Load Splash Screen Config
    std::string splashConfigPath = cwd + "/ui/splash/properties.config";
    std::ifstream splashFile(splashConfigPath);

    bool userWantsSplash = true;
    if (rootConfig.count("SPLASH_SCREEN") && rootConfig.at("SPLASH_SCREEN") == "false") {
        userWantsSplash = false;
    }

    bool useSplash = splashFile.good() && userWantsSplash;

    if (useSplash) {
        auto splashConfig = LoadConfig(splashConfigPath);
        ApplyWindowProperties(w, hwnd, splashConfig, dragBackground);
#ifdef ESD_EMBED_HTML
        std::string splashHtml = GetPageHtml("ui/splash/splash.html");
        if (!splashHtml.empty()) { w.set_html(splashHtml); }
        else { w.navigate("http://127.0.0.1:2024/ui/splash/splash.html?v=" + std::to_string(std::time(nullptr))); }
#else
        w.navigate("http://127.0.0.1:2024/ui/splash/splash.html?v=" + std::to_string(std::time(nullptr)));
#endif
    } else {
        ApplyWindowProperties(w, hwnd, rootConfig, dragBackground);
#ifdef ESD_EMBED_HTML
        std::string mainHtml = GetPageHtml(mainPageFile);
        if (!mainHtml.empty()) { w.set_html(mainHtml); }
        else { w.navigate("http://127.0.0.1:2024/" + mainPageFile + "?v=" + std::to_string(std::time(nullptr))); }
#else
        w.navigate("http://127.0.0.1:2024/" + mainPageFile + "?v=" + std::to_string(std::time(nullptr)));
#endif
#ifdef _WIN32
        if (isFullscreen) ApplyFullscreen(w, hwnd);
#endif
    }

    // 3. Create the JS -> C++ -> Python Bridge
    w.bind("setNativeTitlebarColor", [&](std::string req) -> std::string {
#ifdef _WIN32
        if (hwnd) {
            int r = 255, g = 255, b = 255;
            if (sscanf(req.c_str(), "[\"rgb(%d, %d, %d)\"]", &r, &g, &b) == 3 ||
                sscanf(req.c_str(), "[\"rgba(%d, %d, %d", &r, &g, &b) == 3) {
                COLORREF color = RGB(r, g, b);
                DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, &color, sizeof(color));
            }
        }
#endif
        return "";
    });

    if (titlebarColor == "transparent" && rootConfig.count("TITLEBAR") && rootConfig["TITLEBAR"] != "false") {
        w.init("window.addEventListener('DOMContentLoaded', () => {"
               "  setTimeout(() => {"
               "    let bg = window.getComputedStyle(document.body).backgroundColor;"
               "    if (window.setNativeTitlebarColor) window.setNativeTitlebarColor(bg);"
               "  }, 50);"
               "});");
    }

    w.bind("invokeBridge", [&](std::string req) -> std::string {
        // webview.h sends arguments as a JSON array e.g. ["{...}"]
        // We strip the outer array brackets to parse our raw JSON object string
        std::string payload = "";
        if (req.length() > 2 && req.front() == '[' && req.back() == ']') {
            // Remove the bounding [ ] array markers
            payload = req.substr(1, req.length() - 2);
            // Additional minor unescaping may be necessary depending on JSON payload
        } else {
            payload = req;
        }

        // Reacquire GIL for this callback — the main thread released it before w.run()
        PyGILState_STATE gstate = PyGILState_Ensure();
        std::string pyRes = CallPythonBackend(payload);
        PyGILState_Release(gstate);
        return pyRes;
    });

    // Binding for splash screen to trigger transition
    w.bind("transitionToMain", [&](std::string req) -> std::string {
        ApplyWindowProperties(w, hwnd, rootConfig, dragBackground);
#ifdef ESD_EMBED_HTML
        std::string mainHtml = GetPageHtml(mainPageFile);
        if (!mainHtml.empty()) { w.set_html(mainHtml); }
        else { w.navigate("http://127.0.0.1:2024/" + mainPageFile); }
#else
        w.navigate("http://127.0.0.1:2024/" + mainPageFile);
#endif
#ifdef _WIN32
        if (isFullscreen) ApplyFullscreen(w, hwnd);
#endif
        return "";
    });

    // Window control bindings — usable from any custom titlebar or button
    w.bind("windowClose", [&](std::string req) -> std::string {
#ifdef _WIN32
        if (hwnd) PostMessage(hwnd, WM_CLOSE, 0, 0);
#endif
        return "";
    });

    w.bind("windowMinimize", [&](std::string req) -> std::string {
#ifdef _WIN32
        if (hwnd) ShowWindow(hwnd, SW_MINIMIZE);
#endif
        return "";
    });

    w.bind("windowMaximize", [&](std::string req) -> std::string {
#ifdef _WIN32
        if (hwnd) {
            ShowWindow(hwnd, IsZoomed(hwnd) ? SW_RESTORE : SW_MAXIMIZE);
        }
#endif
        return "";
    });

    // Native Drag window binding for UI
    w.bind("dragWindow", [&](std::string req) -> std::string {
        if (dragBackground) {
#ifdef _WIN32
            if (hwnd) {
                ReleaseCapture();
                SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0);
            }
#endif
        }
        return "";
    });

    // Native External Link opener
    w.bind("openExternalLink", [&](std::string req) -> std::string {
        std::string url = req;
        // The payload arrives as a JSON array string: ["https://example.com"]
        if (url.length() >= 4 && url.front() == '[' && url.back() == ']') {
            url = url.substr(2, url.length() - 4);
        }
#ifdef _WIN32
        ShellExecuteA(0, "open", url.c_str(), 0, 0, SW_SHOW);
#endif
        return "";
    });

    // Inject Javascript to intercept external links
    w.init(R"(
        window.addEventListener('click', function(e) {
            let target = e.target.closest('a');
            if (target && target.href) {
                // Check if it's an external URL (http or https)
                if (target.href.startsWith('http://') || target.href.startsWith('https://')) {
                    e.preventDefault();
                    if (window.openExternalLink) {
                        window.openExternalLink(target.href);
                    }
                }
            }
        });
    )");

    // Holds the JSON payload (set just before openModal) injected into the next
    // modal as window.__esd_payload. Single-threaded message order keeps it paired
    // with its _openModalNative call.
    static std::string g_modalPayload = "null";

    // _openModalSetPayload(payload): stash the runtime payload for the next modal.
    w.bind("_openModalSetPayload", [&](std::string req) -> std::string {
        // req is a JSON array with one element, e.g. [{"mode":"line"}] or [null].
        std::string p = req;
        if (p.size() >= 2 && p.front() == '[' && p.back() == ']')
            p = p.substr(1, p.size() - 2);
        if (p.empty()) p = "null";
        g_modalPayload = p;
        return "";
    });

    // C++ binding: opens a modal HTML file as a native OS window on its own thread.
    // The parent's Promise is resolved when the modal calls closeModal(value).
    w.bind("_openModalNative", [&](std::string req) -> std::string {
        // Payload: JSON array ["modalName"] — strip wrapper
        std::string modalName = req;
        if (modalName.size() >= 4 && modalName.front() == '[' && modalName.back() == ']')
            modalName = modalName.substr(2, modalName.size() - 4);

        std::string modalPath = cwd + "/ui/modals/" + modalName + ".html";
        std::ifstream mf(modalPath);
        if (!mf.is_open()) {
            w.eval("window.__esd_resolveModal(null)");
            return "";
        }
        std::stringstream mss;
        mss << mf.rdbuf();
        std::string src = mss.str();

        // ── Parse <modal> attributes ────────────────────────────────────────
        std::string modalTag = ModalOpenTag(src, "modal");
        int mWidth  = 400, mHeight = 300;
        bool mBlur     = false;
        bool mCloseable = true;
        bool mFullscreen = false;
        bool mTransparent = false;

        if (!modalTag.empty()) {
            try { mWidth  = std::stoi(ModalAttr(modalTag, "width",  "400")); } catch (...) {}
            try { mHeight = std::stoi(ModalAttr(modalTag, "height", "300")); } catch (...) {}
            mBlur        = (ModalAttr(modalTag, "blur",        "false") == "true");
            mCloseable   = (ModalAttr(modalTag, "closeable",   "true")  != "false");
            mFullscreen  = (ModalAttr(modalTag, "fullscreen",  "false") == "true");
            mTransparent = (ModalAttr(modalTag, "transparent", "false") == "true");
        }

        // ── Parse <titlebar> section ────────────────────────────────────────
        // <titlebar value="false"> → custom HTML titlebar, no OS chrome
        // <titlebar value="true">  → use OS native titlebar
        // No <titlebar> element    → use OS native titlebar
        std::string titlebarOpenTag = ModalOpenTag(src, "titlebar");
        bool useOsChrome  = true;
        bool customTitlebar = false;
        int  titlebarH    = 38;
        std::string titlebarHtml;

        if (!titlebarOpenTag.empty()) {
            std::string tbVal = ModalAttr(titlebarOpenTag, "value", "true");
            if (tbVal == "false") {
                useOsChrome   = false;
                customTitlebar = true;
                try { titlebarH = std::stoi(ModalAttr(titlebarOpenTag, "height", "38")); } catch (...) {}
                titlebarHtml = ModalInner(src, "titlebar");
            }
        }

        // ── Parse <title><value>...</value></title> ──────────────────────────
        std::string titleInner  = ModalInner(src, "title");
        std::string windowTitle = ModalInner(titleInner, "value");
        if (windowTitle.empty()) windowTitle = modalName;

        // ── Parse <content> and <script> ────────────────────────────────────
        std::string contentHtml   = ModalInner(src, "content");
        std::string scriptContent = ModalInner(src, "script");

        // ── Generate a full standalone HTML page for the modal window ────────
        std::string tbH = std::to_string(titlebarH);
        std::string generatedHtml;

        if (customTitlebar) {
            generatedHtml =
                "<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><style>"
                "* { margin:0; padding:0; box-sizing:border-box; }"
                "html,body { width:100%; height:100%; overflow:hidden; }"
                ".esd-tb-wrap { position:relative; height:" + tbH + "px; flex-shrink:0; overflow:hidden; }"
                ".esd-tb-drag { position:absolute; inset:0; z-index:0; cursor:move; }"
                ".esd-tb-content { position:relative; z-index:1; height:100%; pointer-events:none; }"
                ".esd-tb-content button,.esd-tb-content input,.esd-tb-content a,"
                ".esd-tb-content select,.esd-tb-content label { pointer-events:auto; }"
                ".esd-body { position:absolute; top:" + tbH + "px; left:0; right:0; bottom:0;"
                " overflow:auto; display:flex; align-items:center; justify-content:center; }"
                "</style></head>"
                "<body style=\"display:flex;flex-direction:column;\">"
                "<div class=\"esd-tb-wrap\">"
                "<div class=\"esd-tb-drag\" onmousedown=\"if(window.dragWindow)dragWindow()\"></div>"
                "<div class=\"esd-tb-content\">" + titlebarHtml + "</div>"
                "</div>"
                "<div class=\"esd-body\">" + contentHtml + "</div>"
                "<script>"
                "window.__esd_payload = " + g_modalPayload + ";"
                "function closeModal(v){if(window._modalClose)window._modalClose(v!==undefined?v:null);}"
                + scriptContent +
                "</script>"
                "</body></html>";
        } else {
            generatedHtml =
                "<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><style>"
                "* { margin:0; padding:0; box-sizing:border-box; }"
                "html,body { width:100%; height:100%; overflow:hidden; }"
                ".esd-body { width:100%; height:100%; display:flex;"
                " align-items:center; justify-content:center; }"
                "</style></head>"
                "<body>"
                "<div class=\"esd-body\">" + contentHtml + "</div>"
                "<script>"
                "window.__esd_payload = " + g_modalPayload + ";"
                "function closeModal(v){if(window._modalClose)window._modalClose(v!==undefined?v:null);}"
                + scriptContent +
                "</script>"
                "</body></html>";
        }

        // ── Optional: blur/dim the parent window while modal is open ─────────
        if (mBlur) {
            w.eval(
                "(function(){"
                "var o=document.createElement('div');"
                "o.id='__esd_blur_overlay__';"
                "o.style.cssText='position:fixed;inset:0;z-index:9998;"
                "backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);"
                "background:rgba(0,0,0,0.35);pointer-events:none;';"
                "document.body.appendChild(o);"
                "})()");
        }

        // ── Read ui/modals/properties.config for corner radius ───────────────
        int mCornerRadius = 0;
        {
            auto modalCfg = LoadConfig(cwd + "/ui/modals/properties.config");
            if (modalCfg.count("CORNER_RADIUS")) {
                try { mCornerRadius = std::stoi(modalCfg.at("CORNER_RADIUS")); } catch (...) {}
            }
        }

        // ── Spawn the modal on its own thread with its own message loop ───────
        auto* params = new ModalThreadParams{
            generatedHtml, windowTitle,
            mWidth, mHeight, mCornerRadius,
            useOsChrome, mCloseable, mFullscreen, mTransparent, devTools,
            &w
        };
        HANDLE hThread = CreateThread(nullptr, 0, ModalWindowThread, params, 0, nullptr);
        if (hThread) CloseHandle(hThread);

        // Payload is consumed by this modal; reset for the next open.
        g_modalPayload = "null";
        return "";
    });

    // JS modal API — openModal(name) returns a Promise resolved by the modal's closeModal(value).
    w.init(R"ESDMODAL(
(function () {
    window.openModal = function (name, payload) {
        return new Promise(function (resolve) {
            window.__esd_modalResolve = resolve;
            // Stash the optional payload (read inside the modal as window.__esd_payload),
            // then open. Message order keeps the two paired.
            window._openModalSetPayload(payload === undefined ? null : payload);
            window._openModalNative(name);
        });
    };

    window.__esd_resolveModal = function (value) {
        var el = document.getElementById('__esd_blur_overlay__');
        if (el) el.remove();
        if (window.__esd_modalResolve) {
            window.__esd_modalResolve(value !== undefined ? value : null);
            window.__esd_modalResolve = null;
        }
    };
})();
)ESDMODAL");

    if (!hideTerminal) {
        std::cout << "Loading Interface..." << std::endl;
    }

    // 4. Run loop
    // Release the GIL so the Python HTTP server daemon thread can process requests.
    // Without this, the main thread holds the GIL through the entire event loop,
    // starving the server thread and producing a black screen.
    PyThreadState* _pyThreadState = PyEval_SaveThread();
    w.run();
    PyEval_RestoreThread(_pyThreadState);

    // 5. Cleanup
    Py_Finalize();
    return 0;
}
