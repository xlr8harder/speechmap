#!/bin/bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless \
  --disable-gpu \
  --screenshot=/Users/jlb/git/speechmap/out.png \
  --window-size=1280,2000 \
  http://localhost:8001
