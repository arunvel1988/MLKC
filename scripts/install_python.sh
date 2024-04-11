#!/bin/bash

# Function to print colored text
print_colored() {
    case $1 in
        "red") echo -e "\033[0;31m$2\033[0m";;
        "green") echo -e "\033[0;32m$2\033[0m";;
        "yellow") echo -e "\033[0;33m$2\033[0m";;
        "blue") echo -e "\033[0;34m$2\033[0m";;
        *) echo "$2";;
    esac
}

# Function to install packages based on the package manager
install_package() {
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y "$1"
    elif command -v yum &>/dev/null; then
        sudo yum install -y "$1"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$1"
    else
        print_colored "red" "Unsupported package manager. Please install $1 manually."
    fi
}

# ASCII art banner
print_colored "blue" "
  ______ _           _      ______ _             _          _____ 
 |  ____| |         | |    |  ____| |           | |        / ____|
 | |__  | | __ _ ___| | __ | |__  | | __ _ _   _| |_ ___  | (___  
 |  __| | |/ _\` / __| |/ / |  __| | |/ _\` | | | | __/ _ \\  \\___ \\ 
 | |    | | (_| \\__ \\   <  | |    | | (_| | |_| | || (_) | ____) |
 |_|    |_|\\__,_|___/_|\\_\\ |_|    |_|\\__,_|\\__,_|\\__\\___/ |_____/ 
                                                                 
"

# Check if Python is installed
if command -v python3 &>/dev/null; then
    print_colored "green" "Python is installed. Let's continue!"
else
    print_colored "yellow" "Python is not installed. No worries, let's install it!"
    install_package "python3"
fi

# Check if pip is installed
if command -v pip3 &>/dev/null; then
    print_colored "green" "pip is installed. Fantastic!"
else
    print_colored "yellow" "pip is not installed. No problem, let's get it installed!"
    install_package "python3-pip"
fi

# Install required packages from requirements.txt
if [ -f "requirements.txt" ]; then
    print_colored "blue" "Installing packages from requirements.txt..."
    pip3 install -r requirements.txt
else
    print_colored "yellow" "requirements.txt not found. Skipping package installation."
fi

print_colored "green" "Setup complete. You're ready to rock your Flask application!"