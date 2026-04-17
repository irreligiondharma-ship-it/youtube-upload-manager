@echo off
echo Setting up YouTube Upload Manager...
python -m venv venv
call venv\Scripts\activate
echo Installing dependencies...
pip install -r requirements.txt
echo Setup complete! To start the app, run: call venv\Scripts\activate ^&^& python main.py
pause