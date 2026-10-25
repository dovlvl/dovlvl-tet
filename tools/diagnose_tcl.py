import ctypes,sys
from pathlib import Path
root=Path(sys.base_prefix)
dll=ctypes.CDLL(str(root/'DLLs/tcl86t.dll'))
dll.Tcl_CreateInterp.restype=ctypes.c_void_p
dll.Tcl_Eval.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
dll.Tcl_GetStringResult.argtypes=[ctypes.c_void_p];dll.Tcl_GetStringResult.restype=ctypes.c_char_p
interp=dll.Tcl_CreateInterp()
for command in ['info patchlevel','info library', 'source {'+str(root/'tcl/tcl8.6/init.tcl').replace('\\','/')+'}', 'set errorInfo']:
    status=dll.Tcl_Eval(interp,command.encode())
    print(status,command,dll.Tcl_GetStringResult(interp).decode(errors='replace'))
