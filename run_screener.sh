#!/bin/bash

# NSE Stock Screener Runner
# This script runs the stock screener tool

echo "=================================================="
echo "NSE Stock Delivery + Volume + 30WMA Screener"
echo "=================================================="
echo ""

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if required files exist
if [ ! -f "tickers.txt" ]; then
    echo "Error: tickers.txt not found"
    echo "Please create tickers.txt with one ticker symbol per line"
    exit 1
fi

if [ ! -f "config.json" ]; then
    echo "Error: config.json not found"
    exit 1
fi

echo "Starting stock screener..."
echo ""

# Run the main script
.venv/bin/python3 main.py

echo ""
echo "=================================================="
echo "Screener execution completed"
echo "Check the output file and stock_screener.log"
echo "=================================================="
