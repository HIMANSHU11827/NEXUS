@echo off
rem Repo-root nexus.cmd — delegates to the PATH'd launcher in
rem C:\Users\himan\bin\nexus.cmd (which calls the uv-managed venv Python).
rem Delegating avoids any space-in-path quoting issues in this repo's path.
call "C:\Users\himan\bin\nexus.cmd" %*
