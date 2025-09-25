# Madden Roster Editor

A powerful, modern, and user-friendly desktop application for viewing and editing Madden roster files. Built with Python, PyQt6, and pandas, this tool provides a rich user interface for in-depth player modification.

<img width="2560" height="1392" alt="image" src="https://github.com/user-attachments/assets/a6e5e5cb-84aa-4af8-8d49-118514ab0a69" />

## About The Project

This project was created to provide a modern, stable, and extensible platform for the Madden modding community. It addresses the need for a tool that can handle complex roster data while providing a fluid and intuitive user experience, complete with features like animated transitions and a contextual player header.

The application reads the roster's cryptic data fields, maps them to human-readable names, and presents them in an organized and editable format. All changes are saved back to the roster file in the correct format.

## Key Features

*   **Full Player Editing:** Modify hundreds of player attributes, from physical ratings and contract details to equipment and traits / styles.
*   **Modern, Animated UI:** A polished user interface with smooth, animated tab transitions and a contextual header that always shows the currently selected player.
*   **Live Highlighting of Edits:** Any changed attribute is highlighted in **_bold/italic_**, showing you exactly what you've changed before you save.
*   **Advanced Tools:**
    *   **OVR Recalculation:** Recalculate a player's Overall Rating based on their attributes and archetype.
    *   **Archetype Regeneration:** Automatically determine the best-fit archetype for a player based on their ratings.
    *   **Portrait ID Copier:** Quickly copy all player portrait IDs from a source roster to your current roster by matching player names and positions.
    *   **Bulk Injury Removal:** Instantly clear all active injuries for every player in the roster.
*   **Live Search & Filtering:** Easily find players by name, position, or team.
*   **Standalone Executable:** Packaged into a single `.exe` file for easy distribution and use without needing Python installed.

## Getting Started

There are two ways to get started with the Madden Roster Editor: as a user or as a developer (coming soon).

### For Users

1.  Go to the **[Releases](https://github.com/kn1meR/Madden26RosterEditor/releases)** page of this GitHub repository.
2.  Download the latest `.zip` file (e.g., `MRE_v1.0.zip`).
3.  Extract the contents.
4.  Run the `MRE.exe` executable.

### For Developers

If you want to run the application from the source code or contribute to its development:

1.  **Prerequisites:**
    *   Python 3.10+
    *   Node.js version 16.20.2 (for the roster I/O script) 

2.  **Clone the repository:**
    ```sh
    git clone https://github.com/kn1meR/MaddenRosterEditor.git
    cd MaddenRosterEditor
    ```

3.  **Create and activate a virtual environment:**
    ```sh
    python -m venv venv
    .\venv\Scripts\activate
    ```

4.  **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

5.  **Run the application:**
    ```sh
    python src/mrepAPI.py
    ```

## Configuration

The application is highly configurable via files located in the `config/` directory.

*   **`config.json`**: The central configuration file. It contains all the necessary data maps:
    *   `header_map`: Translates cryptic roster codes (e.g., `PFNA`) to readable names ("First Name").
    *   `position_map`, `team_map`, `archetype_map`, etc.: Map numeric IDs to their string representations.
*   **`ui_layout.json`**: Defines the entire layout of the player editor, including which attributes appear on which tab and in which group.
*   **`archetype_breakdown.xlsx`**: The spreadsheet used by the Overall and Archetype calculators to determine weights and formulas.
*   **`settings.json`**: This file is created automatically in the same directory as the `.exe` when you first save your settings (e.g., the path to your player images folder).

## Building the Executable

This project uses **PyInstaller** to package the application into a single `.exe` file.

1.  Ensure you have followed the "For Developers" setup steps.
2.  Make sure PyInstaller is installed (`pip install pyinstaller`).
3.  Download the nodejs standalone binary from [here](https://nodejs.org/en/download) and extract it to the project root in a folder named 'node'.
4.  Run the build command from the project's root directory:
    ```sh
    pyinstaller MREP.spec
    ```
5.  The final standalone executable will be located in the `dist/` folder.

## License

Distributed under the MIT License. See `LICENSE` for more information.
