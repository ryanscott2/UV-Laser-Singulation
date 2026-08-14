=====================================================================
 UV LASER WAFER DICING - LASER PC GUIDE
 Windows 7  -  Python 3.8  -  offline
=====================================================================

WHAT THIS DOES
  One command dices a wafer: the Prior OptiScan III stage moves the
  wafer (in the fixed, pinned jig) under the fixed laser field to each
  of the four quadrant positions, and WinLase marks that quadrant's job
  at each stop.

WHAT'S ON THIS USB
  python\   the program (copy these into your program folder):
              optiscan.py             stage driver + jog/teach tool
              dice_wafer.py           the one-command dicer
              winlase_build_jobs.py   builds the WinLase .wlj jobs
              optiscan_positions.json the four stage positions (P1-P4)
              dice_passes.csv         passes-per-station, per set
  wheels\    offline pip packages (pyserial + pywin32)
  tools\     activate.bat / setup.bat helper launchers
  docs\      SETUP.txt (longer setup notes)
  README.txt this file

  On the laser PC everything lives in one folder, e.g.
    C:\Users\samurai\Desktop\UserJobs\GoodsonGroup\Ryan\python\
  with the venv inside it (...\python\venv\) and the wheels inside the
  venv (...\python\venv\wheels\).

---------------------------------------------------------------------
 ONE-TIME SETUP
---------------------------------------------------------------------
 1. Copy the contents of this USB's  python\  folder into your program
    folder (...\Ryan\python\). Copy the  wheels\  folder in too (you keep
    it at ...\python\venv\wheels\).
 2. Confirm Python 3.8.10 is installed and on PATH - in a NEW PowerShell:
        python --version           (must print: Python 3.8.10)
 3. Create the virtual environment inside the program folder:
        cd "C:\Users\samurai\Desktop\UserJobs\GoodsonGroup\Ryan\python"
        python -m venv venv
 4. Allow venv activation for the window, then activate:
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\venv\Scripts\Activate.ps1
    The prompt now shows (venv).
 5. Install the packages from the wheels (offline):
        pip install --no-index --find-links ".\venv\wheels" pyserial pywin32
        python .\venv\Scripts\pywin32_postinstall.py -install

---------------------------------------------------------------------
 EVERY SESSION
---------------------------------------------------------------------
 Open PowerShell in the program folder and activate the venv:
        cd "C:\Users\samurai\Desktop\UserJobs\GoodsonGroup\Ryan\python"
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\venv\Scripts\Activate.ps1
 You should see (venv) in the prompt. Close the WinLase GUI before any
 step that marks - the GUI and the automation can't share the laser.

---------------------------------------------------------------------
 WHAT TO POINT AT  -  <set> is a SLICED SET FOLDER, not a single DXF
---------------------------------------------------------------------
 The wafer pattern is sliced (on the CAD/design PC) into a SET FOLDER with
 one subfolder per station - that whole folder is what you point at:

     <set>\P1\Horizontal.dxf   <set>\P1\Vertical.dxf
     <set>\P2\...   P3\...   P4\...
     <set>\Master\  ,  position_manifest.csv        (bookkeeping)

 Copy the whole set folder onto the laser PC. BOTH winlase_build_jobs.py
 and dice_wafer.py take the SET FOLDER as their argument - never a single
 DXF, and not the individual P1..P4 folders. winlase_build_jobs then adds a
 <set>\WinLaseJobs\ folder with the four .wlj it builds (one per station,
 H + V combined). Example:

     python winlase_build_jobs.py "C:\...\DXFs\081326_AlignmentTest_v2"
     python dice_wafer.py         "C:\...\DXFs\081326_AlignmentTest_v2" --arm --home-after

---------------------------------------------------------------------
 DICING A WAFER
---------------------------------------------------------------------
 1. Build the WinLase jobs for the pattern set (once per set):
        python winlase_build_jobs.py <path-to-set>
    Writes <set>\WinLaseJobs\*.wlj with the fixed settings: parallel
    fill, 0.01 mm spacing, 0 deg (horizontal) / 90 deg (vertical),
    mark-fill on, outline off, 400 mm/s.

 2. Load and tape the wafer in the jig. The jig stays pinned to the
    stage - you never re-seat it; the stage does the moving.

 3. Dry run first (NO laser) - watch the stage index all four spots:
        python dice_wafer.py <path-to-set>

 4. Dice for real:
        python dice_wafer.py <path-to-set> --arm --home-after
    Type DICE at the prompt. It moves P1 -> P2 -> P3 -> P4, marking each
    quadrant. A keypress (or the pre-run countdown) aborts with a
    controlled stop - keep a hand on the hardware e-stop.

---------------------------------------------------------------------
 PASSES (how many times each quadrant is marked)
---------------------------------------------------------------------
 Edit  dice_passes.csv  (next to the scripts):
        set,passes
        081326_AlignmentTest,50
        ...,50
        default,175
 The 'set' is the pattern-set FOLDER name. Alignment tests = 50; any set
 not listed uses the 'default' row (175). For a one-off, override on the
 command line:   python dice_wafer.py <set> --passes 50

---------------------------------------------------------------------
 STAGE POSITIONS
---------------------------------------------------------------------
 optiscan_positions.json holds the four stage coordinates (computed from
 the jig geometry); dice_wafer loads it automatically. To check the stage
 by itself:
        python optiscan.py info                       (comms + position)
        python optiscan.py goto --x 19810 --y 18450   (drive to P1)
        python optiscan.py home                       (drive to 0,0)

---------------------------------------------------------------------
 TROUBLESHOOTING
---------------------------------------------------------------------
 - "could not open port 'COM5': Access is denied"  -> another program
   (Prior software / WinLase / a serial terminal) holds the port. Close
   it, or unplug/replug the OptiScan USB, then retry.
 - "python is not recognized"  -> open a NEW PowerShell (PATH updates
   only reach new windows).
 - A move refused as "outside travel"  -> a bad coordinate; check
   optiscan_positions.json.
=====================================================================
