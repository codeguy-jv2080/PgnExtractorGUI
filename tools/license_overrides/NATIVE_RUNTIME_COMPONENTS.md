# Native runtime component notices

This file documents non-Python components observed in the PgnExtractorGUI
Windows x64 package. The package is built with Python 3.10.6 and PyInstaller
6.22.2; actual package versions are recorded in the adjacent manifest.

## CPython and its bundled libraries

The package includes the CPython 3.10.6 runtime, standard-library extension
modules, and libraries supplied with that runtime, including OpenSSL, libffi,
and SQLite. Their applicable notices are included in
`../python-3.10.6/LICENSE.txt`.

## Python.NET and .NET assemblies

The package includes Python.NET 3.1.0 and its managed runtime assemblies (for
example, `Python.Runtime.dll` and `System.*.dll`) to support pywebview's Windows
Forms backend. Python.NET's MIT license and author notice are included in the
`../pythonnet-3.1.0/` directory. The included .NET assembly license text is
`dotnet-runtime-MIT-LICENSE.txt`. Upstream .NET licensing information and
third-party notices are available at:

- https://github.com/dotnet/runtime/blob/main/LICENSE.TXT
- https://github.com/dotnet/runtime/blob/main/THIRD-PARTY-NOTICES.TXT

## Microsoft WebView2 SDK

The package includes Microsoft WebView2 SDK 1.0.3856.49 assemblies and loaders
used by the Windows Forms backend. `microsoft-webview2-1.0.3856.49-LICENSE.txt`
and `microsoft-webview2-1.0.3856.49-NOTICE.txt` are copied from that exact SDK
package. The SDK package is available at:

https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49

The installed Microsoft Edge WebView2 Runtime is an operating-system component
and is not bundled by this application. Microsoft documents its distribution at:

https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution

## Microsoft Visual C++ runtime files

The package can include Microsoft Visual C++ runtime/API-set files required by
the CPython runtime. The CPython license material above includes Microsoft's
distributable-code terms that apply to the Python distribution.
