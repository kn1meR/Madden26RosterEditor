import sys
import os
import pandas as pd
import numpy as np
import csv
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidgetItem, QLineEdit, QLabel, QTabWidget, QScrollArea, QFormLayout,  # noqa: F401
    QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QStatusBar, QProgressBar, QDateEdit, QHeaderView, QStackedWidget,
    QGraphicsOpacityEffect
)
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtCore import Qt, QDate, QObject, QThread, pyqtSignal, QTimer, QPropertyAnimation
from PIL import Image, ImageQt
from rating_calculator import RatingCalculator
import subprocess
import json
from datetime import datetime, timedelta

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        # This is the path to the bundled files.
        base_path = sys._MEIPASS
    except Exception:
        # sys._MEIPASS is not defined, so we are running in a normal Python environment
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

CONFIG_DIR = get_resource_path('config')
NODE_SCRIPT_PATH = get_resource_path('roster_io.js')
NODE_EXECUTABLE_PATH = get_resource_path(os.path.join('node', 'node.exe'))


IMAGES_FOLDER = "" # folder containing player images

class ArchetypeCalculator:
    def __init__(self, filepath, header_map, position_group_map, all_archetypes_map):
        self.weights = {}
        self.short_to_readable_map = {}
        self.position_group_map = position_group_map
        self.valid_archetypes = set(all_archetypes_map.keys())
        
        try:
            df_weights = pd.read_excel(filepath, sheet_name='Weights', index_col=[0, 1])
            df_desc = pd.read_excel(filepath, sheet_name='Description')
            for index, row in df_desc.iterrows():
                short_name = str(row.iloc[1]).strip()
                readable_name = str(row.iloc[0]).strip()
                self.short_to_readable_map[short_name] = readable_name

            for (position, player_type), ratings in df_weights.iterrows():
                if position not in self.weights:
                    self.weights[position] = {}
                self.weights[position][player_type] = ratings.dropna().to_dict()

            # Get the set of all possible archetype names from PLTYLookup.json
            all_known_archetypes = set(all_archetypes_map.keys())
            
            # Get the set of archetypes we have calculation data for in XLSX
            calculable_archetypes = set(df_weights.index.get_level_values(1))
            
            # Find the archetypes that are in the master list but not in calculation file
            missing_archetypes = all_known_archetypes - calculable_archetypes
            

        except FileNotFoundError:
            QMessageBox.warning(None, "Archetype File Not Found", f"The file was not found at {filepath}")
        except Exception as e:
            QMessageBox.critical(None, "Archetype File Error", f"Failed to parse archetype breakdown file: {e}")

    def calculate_best_archetype(self, player_data: pd.Series) -> str | None:
        player_position = player_data.get("PositionName")
        if not player_position: return None

        archetype_options = self.weights.get(player_position)
        
        if not archetype_options:
            generic_position = self.position_group_map.get(player_position)
            if generic_position:
                archetype_options = self.weights.get(generic_position)
        
        if not archetype_options:
            return None

        # --- NEW, SMARTER LOGIC ---
        
        scores = {}
        # 1. Calculate the score for ALL possible archetypes defined in the Excel file.
        for archetype_name, attribute_weights in archetype_options.items():
            current_score = 0
            for short_name, weight in attribute_weights.items():
                readable_name = self.short_to_readable_map.get(short_name)
                if readable_name:
                    try:
                        player_rating = int(player_data.get(readable_name))
                    except (ValueError, TypeError, KeyError):
                        player_rating = 0
                    current_score += player_rating * weight
            scores[archetype_name] = current_score

        # 2. Filter those scores, keeping only the archetypes that are VALID in the modern game.
        valid_scores = {
            arch: score for arch, score in scores.items() if arch in self.valid_archetypes
        }

        # 3. If no valid options remain after filtering, we cannot proceed.
        if not valid_scores:
            return None

        # 4. Return the valid archetype that has the highest score.
        best_archetype = max(valid_scores, key=valid_scores.get)
        return best_archetype

class OverallCalculator:
    def __init__(self, filepath, header_map, position_group_map):
        self.archetype_data = {}
        self.short_to_readable_map = {}
        self.position_group_map = position_group_map
        
        try:
            df_weights = pd.read_excel(filepath, sheet_name='Weights', index_col=[0, 1])
            df_desc = pd.read_excel(filepath, sheet_name='Description')

            for index, row in df_desc.iterrows():
                short_name = str(row.iloc[1]).strip()
                readable_name = str(row.iloc[0]).strip()
                self.short_to_readable_map[short_name] = readable_name

            for (position, player_type), data in df_weights.iterrows():
                if position not in self.archetype_data:
                    self.archetype_data[position] = {}
                weights = data.drop(['Total', 'DesiredHigh', 'DesiredLow']).dropna().to_dict()
                self.archetype_data[position][player_type] = {
                    'weights': weights,
                    'high': data.get('DesiredHigh', 99),
                    'low': data.get('DesiredLow', 12)
                }
        except FileNotFoundError:
            QMessageBox.warning(None, "Archetype File Not Found", f"The file was not found at {filepath}")
        except Exception as e:
            QMessageBox.critical(None, "Archetype File Error", f"Failed to parse OVR calculation data: {e}")

    def calculate_overall(self, player_data: pd.Series) -> int | None:
        player_position = player_data.get("PositionName")
        player_archetype = player_data.get("Archetype")

        # First, try to get data for the specific position (ex, 'RT')
        archetype_info = self.archetype_data.get(player_position, {}).get(player_archetype)
        
        # If that fails, find the position group (ex, 'OT') and try again.
        if not archetype_info:
            generic_position = self.position_group_map.get(player_position)
            if generic_position:
                archetype_info = self.archetype_data.get(generic_position, {}).get(player_archetype)
        
        # If we still cant find the data, we cannot calculate.
        if not archetype_info:
            return None

        weights = archetype_info['weights']
        desired_high = archetype_info['high']
        desired_low = archetype_info['low']

        weighted_sum = 0
        total_weight = sum(weights.values())
        if total_weight == 0: return None

        for short_name, weight in weights.items():
            readable_name = self.short_to_readable_map.get(short_name)
            if readable_name:
                try:
                    player_rating = int(player_data.get(readable_name))
                except (ValueError, TypeError, KeyError):
                    player_rating = 0
                weighted_sum += player_rating * weight
        
        weighted_average = weighted_sum / total_weight

        if (desired_high - desired_low) == 0: return None
        ovr = (weighted_average - desired_low) * (99 / (desired_high - desired_low))
        if not np.isfinite(ovr):
            return None
        return max(12, min(99, round(ovr)))

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return int(self.text()) < int(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)

class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = current_settings.copy()  # Work on a copy

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Image Folder Path
        self.image_path_edit = QLineEdit(self.settings.get("images_folder", ""))
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.browse_folder)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.image_path_edit)
        path_layout.addWidget(browse_button)

        form_layout.addRow("Player Images Folder:", path_layout)
        layout.addLayout(form_layout)

        # Save and Cancel Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Images Folder")
        if directory:
            self.image_path_edit.setText(directory)

    def on_save(self):
        self.settings["images_folder"] = self.image_path_edit.text()
        self.accept()

    def get_settings(self):
        return self.settings

class ProgressDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        
        # Prevent user from closing the dialog with the 'X' button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        self.setModal(True) # Block interaction with the main window
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)
        
        self.message_label = QLabel("Starting operation...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        self.progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #1265b8;
                width: 10px;
                margin: 0.5px;
            }
        """)

        layout.addWidget(self.message_label)
        layout.addWidget(self.progress_bar)

    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.message_label.setText(message)
        QApplication.processEvents()

class PortraitCopierDialog(QDialog):
    def __init__(self, destination_df, data_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Portrait ID Copier")
        self.destination_df = destination_df
        self.data_manager = data_manager
        
        self.setMinimumSize(600, 400)
        
        # ui setup
        layout = QVBoxLayout(self)
        
        info_label = QLabel("This tool will copy 'Portrait ID' values from a source roster to your currently loaded roster.\n"
                            "Players are matched based on First Name, Last Name, and Position.")
        info_label.setWordWrap(True)
        
        self.start_button = QPushButton("Select Source Roster and Start Copy")
        self.start_button.clicked.connect(self.run_copy_process)
        
        self.status_label = QLabel("Ready to begin.")
        
        # results
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Player Name", "Position", "Old Portrait ID", "New Portrait ID"])
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        
        layout.addWidget(info_label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.results_table)
        layout.addWidget(close_button)

    def run_copy_process(self):
        source_path, _ = QFileDialog.getOpenFileName(self, "Select Source Roster File", "", "All Files (*)")
        if not source_path:
            return

        self.status_label.setText("Loading source roster... Please wait.")
        QApplication.processEvents()

        source_df = self.data_manager._load_raw_player_data(source_path)
        if source_df is None:
            QMessageBox.critical(self, "Error", "Could not load raw player data from the selected source file.")
            self.status_label.setText("Error loading source file.")
            return
        
        self.status_label.setText("Creating source player map...")
        QApplication.processEvents()
        
        portrait_map = {}
        pos_map = self.data_manager.position_map 
        
        for _, player in source_df.iterrows():
            pos_id = player.get('PPOS')
            pos_name = pos_map.get(pos_id, 'Unknown')
            

            key = f"{player.get('PFNA', '')}_{player.get('PLNA', '')}_{pos_name}"
            portrait_map[key] = player.get('PSXP') 


        self.status_label.setText("Matching players and copying IDs...")
        QApplication.processEvents()
        
        changes = []
        for index, player in self.destination_df.iterrows():
            key = f"{player.get('First Name', '')}_{player.get('Last Name', '')}_{player.get('PositionName', '')}"
            
            if key in portrait_map:
                new_portrait_id = portrait_map[key]
                old_portrait_id = player.get('Portrait ID')
                
                if pd.notna(new_portrait_id) and new_portrait_id != old_portrait_id:
                    self.destination_df.at[index, 'Portrait ID'] = new_portrait_id
                    changes.append({
                        "name": f"{player.get('First Name', '')} {player.get('Last Name', '')}",
                        "pos": player.get('PositionName', ''),
                        "old_id": old_portrait_id,
                        "new_id": new_portrait_id
                    })
        
        self._populate_results(changes)
        
        if changes:
            self.status_label.setText(f"Success! Copied {len(changes)} new Portrait IDs. Please save your roster to keep these changes.")
            self.parent().player_editor.mark_dirty()
        else:
            self.status_label.setText("Process complete. No matching players with different Portrait IDs were found.")

    def _populate_results(self, changes):
        self.results_table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            self.results_table.setItem(row, 0, QTableWidgetItem(change['name']))
            self.results_table.setItem(row, 1, QTableWidgetItem(change['pos']))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(change['old_id'])))
            self.results_table.setItem(row, 3, QTableWidgetItem(str(change['new_id'])))

class RosterWorker(QObject):
    load_finished = pyqtSignal(object)
    save_finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)
    progress_updated = pyqtSignal(int)

    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager

    def load_roster(self, path):
        try:
            # Reading the file with Node.js
            self.progress_updated.emit(10)
            command = [NODE_EXECUTABLE_PATH, NODE_SCRIPT_PATH, 'read', path]
            result = subprocess.run(command, capture_output=True, text=True, check=True, shell=True)
            
            # Parsing the huge JSON string from Node.js
            self.progress_updated.emit(50)
            all_data = json.loads(result.stdout)
            
            # Creating the initial pandas DataFrames
            self.progress_updated.emit(60)
            dataframes = {}
            for table_name, records in all_data.items():
                if records:
                    dataframes[table_name] = pd.DataFrame.from_records(records)

            if 'play' not in dataframes:
                self.load_finished.emit(None)
                return

            roster_df = dataframes['play']

            # Merging and cleaning the data
            self.progress_updated.emit(70)
            if 'injy' in dataframes:
                injy_df = dataframes['injy']
                injury_columns_to_merge = ['PGID', 'INIR', 'INJL', 'INJS', 'INJT', 'INSI', 'INTW']
                filtered_injy_df = injy_df[injury_columns_to_merge].copy()
                roster_df = pd.merge(roster_df, filtered_injy_df, on='PGID', how='left')
            
            roster_df = roster_df.loc[:,~roster_df.columns.duplicated()]

            # Mapping IDs to readable text (can be slow)
            self.progress_updated.emit(80)
            
            # Unmapped data calculation
            raw_columns = set(roster_df.columns)
            mapped_cryptic_columns = set(self.data_manager.header_map.keys())
            unmapped_columns = list(raw_columns - mapped_cryptic_columns)
            if unmapped_columns:
                unmapped_data_col = roster_df[unmapped_columns].to_dict('records')

            # Create new display columns
            if 'PPOS' in roster_df.columns:
                roster_df['PositionName'] = pd.to_numeric(roster_df['PPOS'], errors='coerce').astype('Int64').map(self.data_manager.position_map).fillna("Unknown")
            if 'TGID' in roster_df.columns:
                roster_df['TeamName'] = pd.to_numeric(roster_df['TGID'], errors='coerce').astype('Int64').map(self.data_manager.team_map).fillna("Unknown")
            if 'PCOL' in roster_df.columns:
                roster_df['CollegeName'] = pd.to_numeric(roster_df['PCOL'], errors='coerce').astype('Int64').map(self.data_manager.college_map).fillna("Unknown")

            # Rename cryptic columns
            roster_df.rename(columns=self.data_manager.header_map, inplace=True)

            # Map remaining ID columns
            map_configs = {
                'XP Rate/TraitDevelopment': self.data_manager.dev_trait_map,
                'Home State': self.data_manager.state_map,
                'Archetype': self.data_manager.archetype_map,
                'Career Phase': self.data_manager.career_phase_map,
                'QB Style': self.data_manager.throw_style_map
            }
            for col, value_map in map_configs.items():
                if col in roster_df.columns and value_map:
                    roster_df[col] = pd.to_numeric(roster_df[col], errors='coerce').astype('Int64').map(value_map).fillna("Unknown")
            
            if 'DRAFTTEAM' in roster_df.columns and self.data_manager.team_map:
                roster_df['DRAFTTEAM'] = pd.to_numeric(roster_df['DRAFTTEAM'], errors='coerce').astype('Int64').map(self.data_manager.team_map).fillna("None")

            if 'unmapped_data_col' in locals():
                roster_df['UnmappedData'] = unmapped_data_col
            
            dataframes['play'] = roster_df
            
            self.progress_updated.emit(100)
            self.load_finished.emit(dataframes)

        except Exception as e:
            self.error.emit(f"An unexpected error occurred during loading: {e}")

    def save_roster(self, dfs_to_save, original_path, new_path):
        try:
            # Prepare the data for saving
            self.progress_updated.emit(10)
            
            df_play = dfs_to_save['play'].copy()

            REVERSE_MAP_CONFIG = {
                'QB Style': ('PQBS', self.data_manager.inverse_throw_style_map),
                'XP Rate/TraitDevelopment': ('PROL', self.data_manager.inverse_dev_trait_map),
                'Home State': ('PHSN', self.data_manager.inverse_state_map),
                'Archetype': ('PLTY', self.data_manager.inverse_archetype_map),
                'Career Phase': ('PPHS', self.data_manager.inverse_career_phase_map),
                'DRAFTTEAM': ('PTDR', self.data_manager.inverse_team_map)
            }
            for readable_col, (cryptic_col, inverse_map) in REVERSE_MAP_CONFIG.items():
                if readable_col in df_play.columns:
                    df_play[cryptic_col] = df_play[readable_col].map(inverse_map)
            
            display_only_columns = list(REVERSE_MAP_CONFIG.keys()) + ['PositionName', 'TeamName', 'CollegeName', 'UnmappedData']
            df_play.drop(columns=display_only_columns, inplace=True, errors='ignore')

            inverse_header_map = {v: k for k, v in self.data_manager.header_map.items()}
            df_play.rename(columns=inverse_header_map, inplace=True)
            df_play = df_play.loc[:,~df_play.columns.duplicated()]
            
            dfs_to_save['play'] = df_play

            # Convert all tables to JSON
            self.progress_updated.emit(40)
            records_to_save = {}
            for table_name, df in dfs_to_save.items():
                df_copy = df.copy()
                for col in df_copy.select_dtypes(include=np.number).columns:
                    df_copy[col] = df_copy[col].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
                df_copy = df_copy.where(pd.notna(df_copy), None)
                records_to_save[table_name] = df_copy.to_dict('records')

            json_to_pass = json.dumps(records_to_save, allow_nan=False)
            
            # Writing the file with Node.js
            self.progress_updated.emit(60)
            command = [NODE_EXECUTABLE_PATH, NODE_SCRIPT_PATH, 'write', original_path, new_path]
            result = subprocess.run(command, input=json_to_pass, capture_output=True, text=True, check=True, shell=True)
            
            self.progress_updated.emit(100)
            self.save_finished.emit(True, "Save successful.")
            
        except Exception as e:
            self.error.emit(f"An unexpected error occurred during saving: {e}")

class DataManager:
    def __init__(self):
        self.header_map = {}
        self.position_map = {}
        self.team_map = {}
        self.college_map = {}
        self.dev_trait_map = {}
        self.state_map = {}
        self.archetype_map = {}
        self.inverse_archetype_map = {}
        self.career_phase_map = {}
        self.short_to_cryptic_map = {}
        self.throw_style_map = {}
        self.inverse_throw_style_map = {}
        self.inverse_career_phase_map = {}
        self.inverse_dev_trait_map = {}
        self.inverse_position_map = {}
        self.inverse_state_map = {}
        self.inverse_team_map = {}
        self.inverse_throw_style_map = {}
        

        self.position_group_map = {
            'LT': 'OT', 'RT': 'OT',
            'LG': 'G', 'RG': 'G',
            'LEDG': 'DE', 'REDG': 'DE',
            'SAM': 'OLB', 'WILL': 'OLB','MIKE': 'MLB',
            'FS': 'S', 'SS': 'S',
            'K': 'KP', 'P': 'KP'
        }

        self.archetype_conversion_map = {
            'CB_HybridCorner': 'CB_Slot',
            'C_WellRounded': 'C_Agile',
            'DE_PurePower': 'DE_PowerRusher',
            'DT_NoseTackle': 'DT_PowerRusher',
            'DT_PurePower': 'DT_PowerRusher',
            'HB_ElusivePower': 'HB_ElusiveBack',
            'HB_ElusiveReceiving': 'HB_ElusiveBack',
            'HB_PowerBlocking': 'HB_PowerBack',
            'HB_PowerReceiving': 'HB_PowerBack',
            'OT_WellRounded': 'OT_Agile',
            'QB_PureScrambler': 'QB_Scrambler',
            'TE_PhysicalRouteRunner': 'TE_Possession',
            'TE_PossessionBlocking': 'TE_Blocking',
            'WR_GadgetReceiver': 'WR_Slot',
            'WR_PhysicalBlocker': 'WR_Physical',
            'WR_PhysicalRouteRunner': 'WR_Physical',
            'WR_Playmaker': 'WR_DeepThreat',
            'WR_ShiftyRouteRunner': 'WR_Slot'
        }

        self.load_config_from_json()

    def load_config_from_json(self):
        """Loads all simple key-value maps from the main config.json file."""
        try:
            path = os.path.join(CONFIG_DIR, 'config.json')
            with open(path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Populate all the maps from the loaded data
            # convert keys to integers where necessary
            self.header_map = config_data.get("header_map", {})
            self.position_map = {int(k): v for k, v in config_data.get("position_map", {}).items()}
            self.team_map = {int(k): v for k, v in config_data.get("team_map", {}).items()}
            self.college_map = {int(k): v for k, v in config_data.get("college_map", {}).items()}
            self.dev_trait_map = {int(k): v for k, v in config_data.get("dev_trait_map", {}).items()}
            self.state_map = {int(k): v for k, v in config_data.get("state_map", {}).items()}
            self.career_phase_map = {int(k): v for k, v in config_data.get("career_phase_map", {}).items()}
            self.throw_style_map = {int(k): v for k, v in config_data.get("throw_style_map", {}).items()}
            
            # The archetype map is special (Name:ID in JSON)
            # We need both ID:Name (archetype_map) and Name:ID (inverse_archetype_map)
            self.inverse_archetype_map = config_data.get("archetype_map", {})
            self.archetype_map = {v: k for k, v in self.inverse_archetype_map.items()}

            # Generate other inverse maps needed for saving
            self.inverse_position_map = {v: k for k, v in self.position_map.items()}
            self.inverse_team_map = {v: k for k, v in self.team_map.items()}
            self.inverse_dev_trait_map = {v: k for k, v in self.dev_trait_map.items()}
            self.inverse_state_map = {v: k for k, v in self.state_map.items()}
            self.inverse_career_phase_map = {v: k for k, v in self.career_phase_map.items()}
            self.inverse_throw_style_map = {v: k for k, v in self.throw_style_map.items()}

        except FileNotFoundError:
            QMessageBox.critical(None, "Config Error", f"config.json not found in {CONFIG_DIR}. The application cannot start.")
        except json.JSONDecodeError:
            QMessageBox.critical(None, "Config Error", "config.json is malformed. Please check for syntax errors like missing commas or brackets.")
        except Exception as e:
            QMessageBox.critical(None, "Config Error", f"An unexpected error occurred while parsing config.json: {e}")

    def _load_raw_player_data(self, path):
        try:
            command = [NODE_EXECUTABLE_PATH, NODE_SCRIPT_PATH, 'read', path]
            result = subprocess.run(command, capture_output=True, text=True, check=True, shell=True)
            
            all_data = json.loads(result.stdout)

            if 'play' in all_data and all_data['play']:
                return pd.DataFrame.from_records(all_data['play'])
            
            return None # No player data found

        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error in _load_raw_player_data: {e}")
            return None

class ChangesConfirmationDialog(QDialog):
    def __init__(self, old_data, new_ratings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apply Calculated Ratings?")
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Attribute", "Old Value", "New Value", "Change"])
        changes_exist = False
        for attr, new_val in new_ratings.items():
            try: old_val = int(old_data.get(attr, 0))
            except (ValueError, TypeError): old_val = 0
            if old_val != new_val:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(attr))
                self.table.setItem(row, 1, QTableWidgetItem(str(old_val)))
                self.table.setItem(row, 2, QTableWidgetItem(str(new_val)))
                self.table.setItem(row, 3, QTableWidgetItem(f"{new_val - old_val:+}"))
                changes_exist = True
        if changes_exist: layout.addWidget(self.table)
        else: layout.addWidget(QLabel("No changes were calculated for this player."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(changes_exist)
        layout.addWidget(buttons)

class PlayerEditorWidget(QWidget):
    is_dirty_changed = pyqtSignal(bool)
    show_unmapped_requested = pyqtSignal()

    def __init__(self, calculator, data_manager):
        super().__init__()
        self.model = None
        self.calculator = calculator
        self.data_manager = data_manager
        self.settings = {}
        self.player_index = None
        self.editors = {}
        self.labels = {}
        self.original_player_data = {}
        self._is_dirty = False
        self.trait_attributes = set()
        self.current_animation = None
        self.tab_buttons = {}

        # Create the main layout and the main stack widget
        self.main_layout = QHBoxLayout(self)
        self.main_stack = QStackedWidget()
        self.main_layout.addWidget(self.main_stack)

        # 2. create the placeholder
        self.placeholder_label = QLabel("Select a player to edit.")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setFont(QFont("Arial", 16))
        self.main_stack.addWidget(self.placeholder_label)

        # 3. Create the main editor container and add it as the second page (index 1).
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.main_stack.addWidget(self.editor_container)

        # Create the Contextual Header
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: #333; border-radius: 5px; padding: 10px;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(15)

        self.header_portrait = QLabel()
        self.header_portrait.setFixedSize(64, 64)
        header_layout.addWidget(self.header_portrait)

        # A horizontal layout to hold the name and the info side-by-side
        name_and_info_layout = QVBoxLayout()
        name_and_info_layout.setSpacing(0)
        name_and_info_layout.setContentsMargins(0, 0, 0, 0)

        self.header_name_label = QLabel("Player Name")
        self.header_name_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        self.header_name_label.setStyleSheet("""
            color: #FFF;
        """)
        
        self.header_info_label = QLabel("POS | Team")
        self.header_info_label.setFont(QFont("Arial", 11, QFont.Weight.Normal))
        self.header_info_label.setStyleSheet("""
            color: #AAA;
            letter-spacing: 0.5px;
        """)

        name_and_info_layout.addWidget(self.header_name_label)
        name_and_info_layout.addWidget(self.header_info_label)
        
        header_layout.addLayout(name_and_info_layout)

        header_layout.addStretch()

        ovr_layout = QHBoxLayout()
        ovr_layout.setSpacing(0)
        ovr_layout.setContentsMargins(0, 0, 0, 0)

        self.header_ovr_label = QLabel("99")
        self.header_ovr_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))

        ovr_label_text = QLabel("OVR")
        ovr_label_text.setFont(QFont("Arial", 10, QFont.Weight.Normal))
        ovr_label_text.setStyleSheet("color: #BBB;")

        ovr_layout.addWidget(self.header_ovr_label)
        ovr_layout.addWidget(ovr_label_text)

        header_layout.addLayout(ovr_layout)
        
        self.editor_layout.addWidget(header_widget)

        # Animated Tab System
        self.tab_button_layout = QHBoxLayout()
        self.tab_button_layout.setSpacing(0)
        self.stacked_widget_for_pages = QStackedWidget()

        self.editor_layout.addLayout(self.tab_button_layout)
        self.editor_layout.addWidget(self.stacked_widget_for_pages)

    @property
    def is_dirty(self):
        return self._is_dirty

    @is_dirty.setter
    def is_dirty(self, value):
        if self._is_dirty != value:
            self._is_dirty = value
            self.is_dirty_changed.emit(value)

    @staticmethod
    def _serial_to_qdate(serial) -> QDate:
        try:
            serial_num = int(serial)
            if serial_num <= 0:
                return QDate(2000, 1, 1)
            
            base_date = datetime(1944, 1, 1) # incorrect.  fix later
            final_date = base_date + timedelta(days=serial_num)
            return QDate(final_date.year, final_date.month, final_date.day)
        except (ValueError, TypeError):
            return QDate(2000, 1, 1)

    @staticmethod
    def _qdate_to_serial(q_date: QDate) -> int:
        base_date = datetime(1944, 1, 1) # fix later
        current_date = datetime(q_date.year(), q_date.month(), q_date.day())
        delta = current_date - base_date
        return delta.days
        
    @staticmethod
    def _inches_to_feet_inches(inches: int) -> str:
        try:
            inches = int(inches)
            if inches <= 0: return "0' 0\""
            feet = inches // 12
            remaining_inches = inches % 12
            return f"{feet}' {remaining_inches}\""
        except (ValueError, TypeError):
            return "0' 0\""

    @staticmethod
    def _feet_inches_to_inches(height_str: str) -> int:
        try:
            return int(height_str)
        except ValueError:
            try:
                parts = height_str.replace('"', '').split("'")
                feet = int(parts[0].strip())
                inches = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
                return (feet * 12) + inches
            except (ValueError, IndexError):
                return 0

    def _clear_tabs(self):
        for button in self.tab_buttons.keys():
            self.tab_button_layout.removeWidget(button)
            button.deleteLater()
        
        while self.stacked_widget_for_pages.count() > 1:
            widget = self.stacked_widget_for_pages.widget(1)
            self.stacked_widget_for_pages.removeWidget(widget)
            widget.deleteLater()
            
        self.tab_buttons.clear()

    def set_settings(self, settings):
        self.settings = settings

    def set_model(self, model):
        self.model = model
        self._clear_tabs()
        self.editors.clear()
        self.labels.clear()

        ui_structure = self.load_ui_structure()
        self.trait_attributes = {attr for group in ui_structure.get("Traits", {}).values() for attr in group}
        
        for tab_title, groups in ui_structure.items():
            self._create_tab(tab_title, groups)
        
        categorized_attrs = self.get_categorized_attributes()
        advanced_attrs = [col for col in self.model.columns if col not in categorized_attrs]
        if advanced_attrs:
            self._create_tab("Advanced", {"Uncategorized": advanced_attrs})
            
        self.tab_button_layout.addStretch()

    def _change_tab(self, clicked_button):
        if self.current_animation and self.current_animation.state() == QPropertyAnimation.State.Running:
            return

        target_index = self.tab_buttons.get(clicked_button)
        if target_index is None or self.stacked_widget_for_pages.currentIndex() == target_index:
            clicked_button.setChecked(True)
            return

        current_widget = self.stacked_widget_for_pages.currentWidget()
        current_effect = QGraphicsOpacityEffect(current_widget)
        current_widget.setGraphicsEffect(current_effect)
        
        self.fade_out = QPropertyAnimation(current_effect, b"opacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        
        new_widget = self.stacked_widget_for_pages.widget(target_index)
        new_effect = QGraphicsOpacityEffect(new_widget)
        new_widget.setGraphicsEffect(new_effect)

        self.fade_in = QPropertyAnimation(new_effect, b"opacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)

        def on_fade_out_finished():
            self.stacked_widget_for_pages.setCurrentIndex(target_index)
            for btn, idx in self.tab_buttons.items():
                btn.setChecked(idx == target_index)
            self.fade_in.start()

        self.fade_out.finished.connect(on_fade_out_finished)
        self.current_animation = self.fade_out
        self.fade_out.start()

    def load_ui_structure(self):
        try:
            path = os.path.join(CONFIG_DIR, 'ui_layout.json')
            with open(path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            QMessageBox.warning(self, "UI Layout Warning",
                                "Could not load 'ui_layout.json'.\nFalling back to default layout.")
            # Hardcoded fallback structure
            return { "Information": { "Player Details": ['First Name', 'Last Name', 'Age'] } }

    def get_categorized_attributes(self):
        ui_structure = self.load_ui_structure()
        categorized_attrs = set()
        for tab_title, groups in ui_structure.items():
            for group_title, attrs in groups.items():
                for attr in attrs:
                    categorized_attrs.add(attr)
        return categorized_attrs

    def _create_tab(self, title, groups):
        tab_container = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(tab_container)
        tab_layout = QHBoxLayout(tab_container)

        data_container = QVBoxLayout()
        for group_title, attrs in groups.items():
            if group_title == "Image": continue
            
            group_box = QGroupBox(group_title)
            group_layout = QFormLayout(group_box)
            
            for attr in attrs:
                self._create_editor_for_attribute(attr, group_layout)
                
            data_container.addWidget(group_box)
        
        data_container.addStretch()
        tab_layout.addLayout(data_container, 1)

        button = QPushButton(title)
        button.setCheckable(True)
        button.clicked.connect(lambda: self._change_tab(button))
        
        button.setStyleSheet("""
            QPushButton { border: none; padding: 8px 16px; background-color: transparent; color: #AAA; }
            QPushButton:hover { color: #FFF; }
            QPushButton:checked { color: #FFF; border-bottom: 2px solid #4CAF50; }
        """)

        self.tab_button_layout.addWidget(button)
        page_index = self.stacked_widget_for_pages.addWidget(scroll_area)
        self.tab_buttons[button] = page_index

    def _create_editor_for_attribute(self, attr, layout):
        if attr not in self.model.columns: return
        
        editor = None
        label_map = {'PositionName': 'Position', 'Position': 'Position ID', 'CollegeName': 'College', 'College': 'College ID', 'TeamName': 'Team', 'Potential': 'Potential'}
        
        label_text = label_map.get(attr, attr)
        label = QLabel(label_text)
        self.labels[attr] = label
        
        is_trait = attr in self.trait_attributes

        SPECIAL_EDITORS_MAP = {
            'Archetype': self.data_manager.archetype_map,
            'XP Rate/TraitDevelopment': self.data_manager.dev_trait_map,
            'Home State': self.data_manager.state_map,
            'PositionName': self.data_manager.position_map,
            'Career Phase': self.data_manager.career_phase_map,
            'QB Style': self.data_manager.throw_style_map
        }

        if is_trait:
            editor = QCheckBox()
        elif attr in SPECIAL_EDITORS_MAP:
            editor = QComboBox()
            if SPECIAL_EDITORS_MAP[attr]:
                items = list(SPECIAL_EDITORS_MAP[attr].values())
                editor.addItems(["Unknown"] + sorted(items))
            else:
                editor.addItem(f"No {attr} data")
                editor.setEnabled(False)
        elif attr == 'TeamName':
            editor = QComboBox()
            teams = sorted(self.model['TeamName'].unique())
            editor.addItems(["Unknown"] + list(teams))
        elif attr == 'DRAFTTEAM':
            editor = QComboBox()
            if self.data_manager.team_map:
                editor.addItems(["None"] + sorted(list(self.data_manager.team_map.values())))
        elif attr == 'Height':
            editor = QLineEdit()
            editor.setMinimumWidth(120)
        else:
            column_data = self.model[attr]
            if isinstance(column_data, pd.DataFrame):
                dtype = column_data.iloc[:, 0].dtype
            else:
                dtype = column_data.dtype

            if pd.api.types.is_numeric_dtype(dtype):
                editor = QSpinBox()
                editor.setRange(-999999, 999999)
                editor.setMinimumWidth(100)
            else:
                editor = QLineEdit()
                editor.setMinimumWidth(120)

        # source of truth for adding widgets and signals
        if editor:
            if isinstance(editor, QComboBox):
                editor.currentTextChanged.connect(lambda text, a=attr: self._on_field_changed(a))
            elif isinstance(editor, QSpinBox):
                editor.valueChanged.connect(lambda val, a=attr: self._on_field_changed(a))
            elif isinstance(editor, QCheckBox):
                editor.stateChanged.connect(lambda state, a=attr: self._on_field_changed(a))
            else:
                editor.textChanged.connect(lambda text, a=attr: self._on_field_changed(a))
            
            layout.addRow(label, editor)
            
            self.editors[attr] = editor

    def clear_editor(self):
        self.main_stack.setCurrentIndex(0) # Show placeholder
        self.player_index = None
        self.is_dirty = False

    def _on_field_changed(self, attr):
        self.mark_dirty() # Keep main window title update logic

        editor = self.editors.get(attr)
        label = self.labels.get(attr)
        original_value = self.original_player_data.get(attr)

        if not editor or not label:
            return

        current_value = None
        if isinstance(editor, QComboBox):
            current_value = editor.currentText()
        elif isinstance(editor, QSpinBox):
            current_value = editor.value()
        elif isinstance(editor, QCheckBox):
            current_value = editor.isChecked()
        else: 
            current_value = editor.text()
            
        if attr == 'Height':
            current_value = self._feet_inches_to_inches(str(current_value))
        elif attr == 'Weight':
            current_value = int(current_value) - 160

        is_different = str(current_value) != str(original_value)

        font = label.font()
        font.setBold(is_different)
        font.setItalic(is_different)
        font.setUnderline(is_different)
        label.setFont(font)

    def _reset_all_label_styles(self):
        for label in self.labels.values():
            font = label.font()
            font.setBold(False)
            font.setItalic(False)
            font.setUnderline(False)
            label.setFont(font)

    def load_player(self, index):
        if self.is_dirty:
            reply = QMessageBox.question(self, 'Unsaved Changes', 'You have unsaved changes. Save before switching?', QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save: self.apply_changes()
            elif reply == QMessageBox.StandardButton.Cancel: return False
                
        if index is None or self.model is None or index >= len(self.model):
            self.clear_editor()
            return True

        self._reset_all_label_styles()
        self.player_index = index
        player_data = self.model.loc[self.player_index]
        self.original_player_data = player_data.to_dict()

        # Populate Header
        first_name = player_data.get('First Name', '')
        last_name = player_data.get('Last Name', '')
        pos = player_data.get('PositionName', 'N/A')
        team = player_data.get('TeamName', 'N/A')
        overall = int(player_data.get('Overall', 0))
        
        self.header_name_label.setText(f"{first_name} {last_name}")
        self.header_info_label.setText(f"{pos} | {team}")
        self.header_ovr_label.setText(str(overall))

        portrait_id = player_data.get("Portrait ID")
        if isinstance(portrait_id, pd.Series): portrait_id = portrait_id.iloc[0]
        self._load_player_image(str(portrait_id) if pd.notna(portrait_id) else None)

        # Switch to the editor view
        self.main_stack.setCurrentIndex(1)

        # Set the initial tab if this is the first load
        if self.stacked_widget_for_pages.currentIndex() < 1:
            first_button = next(iter(self.tab_buttons), None)
            if first_button:
                self.stacked_widget_for_pages.setCurrentIndex(self.tab_buttons[first_button])
                first_button.setChecked(True)

        for attr, editor in self.editors.items():
            if attr in player_data:
                value = player_data[attr]
                if isinstance(value, pd.Series): value = value.iloc[0]

                editor.blockSignals(True)

                if attr == 'Height':
                    editor.setText(self._inches_to_feet_inches(value))
                elif attr == 'Weight':
                    editor.setValue(int(value) + 160 if pd.notna(value) else 160)
                elif isinstance(editor, QDateEdit):
                    editor.setDate(self._serial_to_qdate(value))
                elif isinstance(editor, QLineEdit):
                    editor.setText(str(value) if pd.notna(value) else "")
                elif isinstance(editor, QSpinBox):
                    # Apply color coding here
                    editor.setValue(int(value) if pd.notna(value) else 0)
                elif isinstance(editor, QComboBox):
                    editor.setCurrentText(str(value) if pd.notna(value) else "")
                elif isinstance(editor, QCheckBox):
                    editor.setChecked(bool(value))
                
                editor.blockSignals(False)

        if hasattr(self, 'image_label'):
            portrait_id = player_data.get("Portrait ID")
            if isinstance(portrait_id, pd.Series): portrait_id = portrait_id.iloc[0]
            self._load_player_image(str(portrait_id) if pd.notna(portrait_id) else None)
        
        self.is_dirty = False
        return True

    def mark_dirty(self):
        self.is_dirty = True
         
    def apply_changes(self):
        if self.player_index is not None and self.model is not None:
            for attr, editor in self.editors.items():
                if not editor.isEnabled():
                    continue

                new_value = None
                if isinstance(editor, QDateEdit):
                    new_value = self._qdate_to_serial(editor.date())
                elif isinstance(editor, QLineEdit): new_value = editor.text()
                elif isinstance(editor, QSpinBox): new_value = editor.value()
                elif isinstance(editor, QComboBox): new_value = editor.currentText()
                elif isinstance(editor, QCheckBox): new_value = int(editor.isChecked())
                
                if attr == 'Height':
                    new_value = self._feet_inches_to_inches(editor.text())
                elif attr == 'Weight':
                    new_value = editor.value() - 160
                
                elif attr == 'Archetype':
                    self.model.loc[self.player_index, 'Archetype'] = new_value
                    if new_value in self.data_manager.inverse_archetype_map:
                        self.model.loc[self.player_index, 'PLTY'] = self.data_manager.inverse_archetype_map[new_value]
                elif attr == 'XP Rate/TraitDevelopment':
                    self.model.loc[self.player_index, 'XP Rate/TraitDevelopment'] = new_value
                    if new_value in self.data_manager.inverse_dev_trait_map:
                        self.model.loc[self.player_index, 'PROL'] = self.data_manager.inverse_dev_trait_map[new_value]
                elif attr == 'Home State':
                    self.model.loc[self.player_index, 'Home State'] = new_value
                    if new_value in self.data_manager.inverse_state_map:
                        self.model.loc[self.player_index, 'PHSN'] = self.data_manager.inverse_state_map[new_value]
                elif attr == 'PositionName':
                    self.model.loc[self.player_index, 'PositionName'] = new_value
                    if new_value in self.data_manager.inverse_position_map:
                        self.model.loc[self.player_index, 'PPOS'] = self.data_manager.inverse_position_map[new_value]
                elif attr == 'TeamName':
                    self.model.loc[self.player_index, 'TeamName'] = new_value
                    if new_value in self.data_manager.inverse_team_map:
                        self.model.loc[self.player_index, 'TGID'] = self.data_manager.inverse_team_map[new_value]
                elif attr == 'Career Phase':
                    self.model.loc[self.player_index, 'Career Phase'] = new_value
                    if new_value in self.data_manager.inverse_career_phase_map:
                        self.model.loc[self.player_index, 'PPHS'] = self.data_manager.inverse_career_phase_map[new_value]
                elif attr == 'DRAFTTEAM':
                    self.model.loc[self.player_index, 'DRAFTTEAM'] = new_value
                    if new_value in self.data_manager.inverse_team_map:
                        self.model.loc[self.player_index, 'PTDR'] = self.data_manager.inverse_team_map[new_value]
                else:
                    self.model.loc[self.player_index, attr] = new_value
            
            self.is_dirty = False
            self.original_player_data = self.model.loc[self.player_index].to_dict()
            self._reset_all_label_styles()
            return True
        return False
        
    def _load_player_image(self, portrait_id):
        target_label = self.header_portrait
        
        target_label.clear()
        images_folder = self.settings.get("images_folder")
        if not portrait_id: target_label.setText("No\nImg"); return
        if not images_folder or not os.path.isdir(images_folder):
            target_label.setText("Set Img\nFolder"); return
        
        path = os.path.join(images_folder, f"{portrait_id}.dds")
        if not os.path.exists(path): target_label.setText("No\nImg"); return
        try:
            with Image.open(path) as img:
                img = img.convert("RGBA")
                qim = ImageQt.ImageQt(img)
                pixmap = QPixmap.fromImage(qim).scaled(target_label.size(), 
                                                       Qt.AspectRatioMode.KeepAspectRatio, 
                                                       Qt.TransformationMode.SmoothTransformation)
                target_label.setPixmap(pixmap)
        except Exception as e:
            print(f"Failed to load image {path}: {e}")
            target_label.setText("Error")

class RosterEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.progress_dialog = None
        self.settings = {}
        self.load_settings() # Load settings from file on startup
        
        self.roster_file_path = None
        self.base_title = "Madden Roster Editor"
        self.setWindowTitle(self.base_title)
        self.resize(1500, 1200)
        
        self.model = None
        self.team_df = None
        self.depthchart_df = None
        self.filtered_model_indices = None
        
        self.sort_column = 2 # Default to the 'Overall' column (index 2)
        self.sort_order = Qt.SortOrder.DescendingOrder

        self.data_manager = DataManager()
        
        formulas_path = os.path.join(CONFIG_DIR, 'Formulas_and_Methods.txt')
        self.calculator = RatingCalculator(formulas_path, self.data_manager.header_map)

        archetype_breakdown_path = os.path.join(CONFIG_DIR, 'archetype_breakdown.xlsx')
        self.archetype_calculator = ArchetypeCalculator(
            archetype_breakdown_path,
            self.data_manager.header_map,
            self.data_manager.position_group_map,
            self.data_manager.inverse_archetype_map
        )
        self.overall_calculator = OverallCalculator(
            archetype_breakdown_path,
            self.data_manager.header_map,
            self.data_manager.position_group_map
        )
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.worker_thread = QThread()
        self.roster_worker = RosterWorker(self.data_manager)
        self.roster_worker.moveToThread(self.worker_thread)
        
        # Build UI and connect all signals
        self.setup_ui()
        self.connect_signals()

        self.worker_thread.start()

    def setup_ui(self):
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QHBoxLayout(self.main_widget)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        controls_layout = QHBoxLayout()
        self.load_button = QPushButton("Load Roster")
        self.save_button = QPushButton("Save Roster")
        self.save_button.setEnabled(False)
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.save_button)
        left_layout.addLayout(controls_layout)
        filter_group_box = QWidget()
        filter_layout = QFormLayout(filter_group_box)
        filter_layout.setContentsMargins(0, 5, 0, 5)
        self.search_box = QLineEdit()
        self.position_filter = QComboBox()
        self.team_filter = QComboBox()
        self.reset_filters_button = QPushButton("Reset Filters")
        filter_layout.addRow(QLabel("Search:"), self.search_box)
        filter_layout.addRow(QLabel("Position:"), self.position_filter)
        filter_layout.addRow(QLabel("Team:"), self.team_filter)
        filter_layout.addRow(self.reset_filters_button)
        left_layout.addWidget(filter_group_box)
        self.player_list = QTableWidget()
        self.player_list.setColumnCount(4)
        self.player_list.setHorizontalHeaderLabels(["Name", "Position", "Overall", "Age"])
        self.player_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.player_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.player_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.player_list.verticalHeader().setVisible(False)
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        self.settings_action = file_menu.addAction("Settings...")
        self.player_list.setSortingEnabled(True)

        header = self.player_list.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        menu_bar = self.menuBar()
        tools_menu = menu_bar.addMenu("Tools")
        self.convert_archetypes_action = tools_menu.addAction("Convert Old Archetypes")
        self.fix_invalid_archetypes_action = tools_menu.addAction("Fix Logically Invalid Archetypes")
        self.regen_all_archetypes_action = tools_menu.addAction("Regenerate All Archetypes")
        tools_menu.addSeparator()
        self.recalc_all_ovrs_action = tools_menu.addAction("Recalculate All Overalls")
        tools_menu.addSeparator()
        self.remove_all_injuries_action = tools_menu.addAction("Remove All Injuries")
        self.remove_all_injuries_action.setEnabled(False)
        tools_menu.addSeparator()
        self.debug_save_action = tools_menu.addAction("Debug Save Process")
        self.debug_save_action.setEnabled(False)
        tools_menu.addSeparator()
        self.copy_portraits_action = tools_menu.addAction("Copy Portrait IDs from Roster...")
        self.copy_portraits_action.setEnabled(False)
        
        self.convert_archetypes_action.setEnabled(False)
        self.regen_all_archetypes_action.setEnabled(False) # Disabled until roster is loaded
        self.recalc_all_ovrs_action.setEnabled(False)
        self.fix_invalid_archetypes_action.setEnabled(False)

        self.recalc_ovr_button = QPushButton("Recalculate OVR")
        self.recalc_ovr_button.setEnabled(False)

        left_layout.addWidget(self.player_list)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.player_editor = PlayerEditorWidget(self.calculator, self.data_manager)
        button_layout = QHBoxLayout()


        self.show_unmapped_button = QPushButton("Show Unmapped Data")
        self.show_unmapped_button.setEnabled(False)
        self.regen_archetype_button = QPushButton("Regenerate Archetype")
        self.regen_archetype_button.setEnabled(False)
        self.debug_player_button = QPushButton("Debug Player")
        self.debug_player_button.setEnabled(False)

        button_layout.addWidget(self.recalc_ovr_button)
        button_layout.addWidget(self.regen_archetype_button)
        button_layout.addWidget(self.show_unmapped_button)
        button_layout.addWidget(self.debug_player_button)

        right_layout.addLayout(button_layout)
        right_layout.addWidget(self.player_editor)
        self.layout.addWidget(left_panel, 1)
        self.layout.addWidget(right_panel, 2)

    def connect_signals(self):
        self.load_button.clicked.connect(self.load_roster_file)
        self.save_button.clicked.connect(self.save_roster_file)
        self.player_list.cellClicked.connect(self.on_player_selected)
        self.settings_action.triggered.connect(self.open_settings_dialog)
        self.search_box.textChanged.connect(self.apply_filters)
        self.position_filter.currentIndexChanged.connect(self.apply_filters)
        self.team_filter.currentIndexChanged.connect(self.apply_filters)
        self.reset_filters_button.clicked.connect(self.reset_filters)
        self.show_unmapped_button.clicked.connect(self.show_unmapped_player_data)
        self.regen_archetype_button.clicked.connect(self.regenerate_player_archetype)
        self.regen_all_archetypes_action.triggered.connect(self.regenerate_all_archetypes)
        self.recalc_ovr_button.clicked.connect(self.recalculate_player_overall)
        self.recalc_all_ovrs_action.triggered.connect(self.recalculate_all_overalls)
        self.convert_archetypes_action.triggered.connect(self.convert_old_archetypes)
        self.remove_all_injuries_action.triggered.connect(self.remove_all_injuries)
        self.debug_player_button.clicked.connect(self.debug_player_archetype)
        self.fix_invalid_archetypes_action.triggered.connect(self.fix_logically_invalid_archetypes)
        self.debug_save_action.triggered.connect(self.diagnose_save_process)
        self.copy_portraits_action.triggered.connect(self.open_portrait_copier)

        self.roster_worker.load_finished.connect(self.on_load_finished)
        self.roster_worker.save_finished.connect(self.on_save_finished)
        self.roster_worker.error.connect(self.on_worker_error)
        self.roster_worker.progress_updated.connect(self.update_progress_bar)
        self.player_editor.is_dirty_changed.connect(self.set_window_dirty_status)

    def update_progress_bar(self, value):
        if self.progress_dialog:
            message = f"Processing... ({value}%)"
            self.progress_dialog.update_progress(value, message)

    def load_settings(self):
        try:
            with open('settings.json', 'r') as f:
                self.settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If file doesn't exist or is invalid, use defaults
            self.settings = {
                "images_folder": "" 
            }

    def save_settings(self):
        with open('settings.json', 'w') as f:
            json.dump(self.settings, f, indent=4)

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            self.save_settings()
            QMessageBox.information(self, "Settings Saved", 
                                    "Settings have been saved. Please re-select a player to see image changes.")

    def show_unmapped_player_data(self):
        if self.player_editor.player_index is None or self.model is None:
            QMessageBox.warning(self, "No Player Selected", "Please select a player from the list first.")
            return

        if 'UnmappedData' not in self.model.columns:
            QMessageBox.information(self, "No Unmapped Data", "No unmapped data was found in this roster file.")
            return
            
        player_index = self.player_editor.player_index
        unmapped_data = self.model.loc[player_index, 'UnmappedData']
        
        dialog = RawDataDialog(unmapped_data, self)
        dialog.exec()

    def convert_old_archetypes(self):
        if self.model is None: return

        conversion_map = self.data_manager.archetype_conversion_map
        old_archetypes = list(conversion_map.keys())

        players_to_convert = self.model[self.model['Archetype'].isin(old_archetypes)]
        num_to_convert = len(players_to_convert)

        if num_to_convert == 0:
            QMessageBox.information(self, "No Players Found", "No players with old archetypes were found in the roster.")
            return

        reply = QMessageBox.question(self, "Confirm Conversion",
                                    f"Found {num_to_convert} players with old archetypes that can be converted.\n\n"
                                    "This will update their archetype to a new, valid one. This action cannot be undone.\n\n"
                                    "Do you want to continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        self.progress_dialog = ProgressDialog("Converting Old Archetypes...", self)
        self.progress_dialog.show()
        
        changes_made = 0
        processed_count = 0
        inverse_archetype_map = self.data_manager.inverse_archetype_map

        for index, player in players_to_convert.iterrows():
            processed_count += 1
            progress = int((processed_count / num_to_convert) * 100)
            self.progress_dialog.update_progress(progress, f"Processing {processed_count}/{num_to_convert}...")

            current_archetype = player['Archetype']
            new_archetype = conversion_map.get(current_archetype)
            
            if new_archetype:
                new_id = inverse_archetype_map.get(new_archetype)
                if new_id is not None:
                    self.model.at[index, 'Archetype'] = new_archetype
                    self.model.at[index, 'PLTY'] = new_id
                    changes_made += 1

        self.progress_dialog.close()
        self.progress_dialog = None

        self.status_bar.showMessage(f"Conversion complete. {changes_made} players were updated.", 5000)
        
        if changes_made > 0:
            self.player_editor.mark_dirty()
            if self.player_editor.player_index is not None:
                self.player_editor.load_player(self.player_editor.player_index)

    def regenerate_player_archetype(self):
        if self.player_editor.player_index is None or self.model is None:
            QMessageBox.warning(self, "No Player Selected", "Please select a player first.")
            return

        player_data = self.model.loc[self.player_editor.player_index]
        current_archetype = player_data.get("Archetype")

        new_archetype = self.archetype_calculator.calculate_best_archetype(player_data)

        if not new_archetype:
            QMessageBox.information(self, "Calculation Failed", "Could not calculate an archetype for this player's position.")
            return

        if new_archetype == current_archetype:
            QMessageBox.information(self, "No Change", f"The calculated best archetype ({new_archetype}) is already assigned.")
            return

        reply = QMessageBox.question(self, "Apply New Archetype?",
                                     f"Current Archetype: {current_archetype}\n"
                                     f"Calculated Best: {new_archetype}\n\n"
                                     "Do you want to apply this change?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:

            archetype_editor = self.player_editor.editors.get('Archetype')
            
            if archetype_editor:
                archetype_editor.setCurrentText(new_archetype)
                QMessageBox.information(self, "Change Staged", 
                                        "Archetype has been updated in the editor.\n"
                                        "Click 'Save Roster' to make the change permanent.")
            else:
                QMessageBox.critical(self, "Error", "Could not find the Archetype editor widget.")

    def regenerate_all_archetypes(self):
        if self.model is None: return

        reply = QMessageBox.question(self, "Confirm Action",
                                    "This will recalculate the archetype for EVERY player in the roster. "
                                    "This can take a moment and cannot be undone.\n\nAre you sure you want to continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        num_players = len(self.model)
        self.progress_dialog = ProgressDialog("Regenerating All Archetypes...", self)
        self.progress_dialog.show()
        QApplication.processEvents() # Force UI update

        changes_made = 0
        processed_count = 0
        for index, player_data in self.model.iterrows():
            processed_count += 1
            progress = int((processed_count / num_players) * 100)
            self.progress_dialog.update_progress(progress, f"Processing {processed_count}/{num_players}...")

            new_archetype = self.archetype_calculator.calculate_best_archetype(player_data)
            if new_archetype and new_archetype != player_data.get("Archetype"):
                new_id = self.data_manager.inverse_archetype_map.get(new_archetype)
                if new_id is not None:
                    self.model.at[index, 'Archetype'] = new_archetype
                    self.model.at[index, 'PLTY'] = new_id
                    changes_made += 1
        
        self.progress_dialog.close()
        self.progress_dialog = None
        self.status_bar.showMessage(f"Archetype regeneration complete. {changes_made} players were updated.", 5000)
        
        if changes_made > 0:
            self.player_editor.mark_dirty()
            if self.player_editor.player_index is not None:
                self.player_editor.load_player(self.player_editor.player_index)

    def recalculate_player_overall(self):
        if self.player_editor.player_index is None or self.model is None:
            return

        player_index = self.player_editor.player_index
        player_data = self.model.loc[player_index]
        current_ovr = player_data.get("Overall", 0)

        new_ovr = self.overall_calculator.calculate_overall(player_data)

        if new_ovr is None:
            QMessageBox.information(self, "Calculation Failed",
                                    "Could not calculate OVR. The player's archetype or position may not be in the breakdown file.")
            return
        
        if new_ovr == current_ovr:
            QMessageBox.information(self, "No Change", f"The calculated OVR ({new_ovr}) matches the current OVR.")
            return

        reply = QMessageBox.question(self, "Apply New OVR?",
                                    f"Current OVR: {current_ovr}\n"
                                    f"Calculated OVR: {new_ovr}\n\n"
                                    "Do you want to apply this change?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.model.at[player_index, 'Overall'] = new_ovr
            self.player_editor.mark_dirty()
            # Refresh the player list to show the new OVR
            self.refresh_player_list()
            # Re-select and reload the player in the editor
            self.player_list.selectRow(list(self.model.index).index(player_index))
            self.player_editor.load_player(player_index)

    def recalculate_all_overalls(self):
        if self.model is None: return

        reply = QMessageBox.question(self, "Confirm Action",
                                    "This will recalculate the OVR for EVERY player in the roster based on their current archetype. "
                                    "This can take a moment and cannot be undone.\n\nAre you sure you want to continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        num_players = len(self.model)
        self.progress_dialog = ProgressDialog("Recalculating All Overalls...", self)
        self.progress_dialog.show()

        changes_made = 0
        processed_count = 0
        for index, player_data in self.model.iterrows():
            processed_count += 1
            progress = int((processed_count / num_players) * 100)
            self.progress_dialog.update_progress(progress, f"Processing {processed_count}/{num_players}...")

            new_ovr = self.overall_calculator.calculate_overall(player_data)
            if new_ovr is not None and new_ovr != player_data.get("Overall"):
                self.model.at[index, 'Overall'] = new_ovr
                changes_made += 1
        

        self.progress_dialog.close()
        self.progress_dialog = None
        
        self.status_bar.showMessage(f"OVR recalculation complete. {changes_made} players were updated.", 5000)
        
        if changes_made > 0:
            self.player_editor.mark_dirty()
            self.refresh_player_list()
            if self.player_editor.player_index is not None:
                try:
                    row_index = list(self.filtered_model_indices).index(self.player_editor.player_index)
                    self.player_list.selectRow(row_index)
                except ValueError:
                    pass

    def debug_calculator_data(self):
        if self.player_editor.player_index is None or self.model is None:
            print("\nDEBUG: Please select a player first.")
            return

        player_data = self.model.loc[self.player_editor.player_index]
        
        print("\n" + "="*50)
        print("DEBUGGING CALCULATOR DATA")
        print("="*50)

        lookup_map = self.overall_calculator.short_to_readable_map
        print("\n[1] The Calculator's Lookup Map (Short Name -> Readable Name):")
        for i, (key, value) in enumerate(lookup_map.items()):
            if i >= 10: break
            print(f"  '{key}': '{value}'")
        print("  ...")

        print("\n[2] The Player's Actual Data (First 20 Attributes):")
        player_data_sample = player_data.head(20).to_dict()
        for key, value in player_data_sample.items():
            print(f"  '{key}': {value}")
        print("  ...")
        
        print("\n" + "="*50)
        print("Compare the 'Readable Name' from [1] with the keys from [2].")
        print("They must match EXACTLY for the calculation to work.")
        print("Please copy and paste this entire block of text in your reply.")
        print("="*50 + "\n")

    def load_roster_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Madden Roster", "", "All Files (*)")
        if path:
            self.roster_file_path = path
            self.status_bar.showMessage("Loading roster, please wait...")
            self.progress_dialog = ProgressDialog("Loading Roster...", self)
            self.progress_dialog.show()
            self.load_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.roster_worker.load_roster(self.roster_file_path)

    def on_load_finished(self, dfs):
        QTimer.singleShot(0, lambda: self._process_load_finished(dfs))

    def _process_load_finished(self, dfs):
        if self.progress_dialog:
            self.progress_dialog.close()

        self.load_button.setEnabled(True)
        
        if dfs and 'play' in dfs:
            filename = os.path.basename(self.roster_file_path)
            self.base_title = f"Madden Roster Editor - {filename}"
            self.setWindowTitle(self.base_title)

            self.model = dfs['play']
            self.team_df = dfs.get('team')
            self.depthchart_df = dfs.get('dcht')

            self.model['Overall'] = pd.to_numeric(self.model['Overall'], errors='coerce').fillna(0)
            self.player_editor.set_settings(self.settings)
            self.player_editor.set_model(self.model)
            self.populate_filters()
            self.apply_filters()
            self.save_button.setEnabled(True)
            self.regen_all_archetypes_action.setEnabled(True)
            self.recalc_all_ovrs_action.setEnabled(True)
            self.convert_archetypes_action.setEnabled(True)
            self.remove_all_injuries_action.setEnabled(True)
            self.fix_invalid_archetypes_action.setEnabled(True)
            self.debug_save_action.setEnabled(True)
            self.copy_portraits_action.setEnabled(True)
            
            self.status_bar.showMessage(f"Roster '{filename}' loaded.", 5000)
        else:
            self.base_title = "Madden Roster Editor"
            self.setWindowTitle(self.base_title)
            self.status_bar.showMessage("Failed to load roster or find PLAY table.", 5000)

    def save_roster_file(self):
        if self.model is None or self.roster_file_path is None:
            return
        
        path, _ = QFileDialog.getSaveFileName(self, "Save Madden Roster", "", "All Files (*)")
        if path:
            self.player_editor.apply_changes()
            
            dataframes_to_save = {'play': self.model}
            if self.team_df is not None:
                dataframes_to_save['team'] = self.team_df
            if self.depthchart_df is not None:
                dataframes_to_save['dcht'] = self.depthchart_df
            
            self.status_bar.showMessage(f"Saving roster to '{os.path.basename(path)}'...")
            self.progress_dialog = ProgressDialog("Saving Roster...", self)
            self.progress_dialog.show()
            self.load_button.setEnabled(False)
            self.save_button.setEnabled(False)
            
            self.roster_worker.save_roster(dataframes_to_save, self.roster_file_path, path)

    def on_save_finished(self, success, message):
        QTimer.singleShot(0, lambda: self._process_save_finished(success, message))

    def _process_save_finished(self, success, message):
        if self.progress_dialog:
            self.progress_dialog.close()
        self.save_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.regen_archetype_button.setEnabled(True)
        if success:
            self.player_editor.is_dirty = False
            self.status_bar.showMessage("Roster saved successfully.", 5000)
        else:
            QMessageBox.critical(self, "Error", message)
            self.status_bar.showMessage("Failed to save roster.", 5000)

    def on_worker_error(self, message):
        if self.progress_dialog:
            self.progress_dialog.close()
        self.save_button.setEnabled(True)
        self.load_button.setEnabled(True)
        QMessageBox.critical(self, "Operation Error", message)
        self.status_bar.showMessage("An error occurred.", 5000)

    def populate_filters(self):
        self.position_filter.blockSignals(True)
        self.team_filter.blockSignals(True)
        
        self.position_filter.clear()
        self.team_filter.clear()
        
        self.position_filter.addItem("All Positions")
        self.team_filter.addItem("All Teams")

        if self.data_manager.position_map:
            sorted_positions_by_id = sorted(self.data_manager.position_map.items(), key=lambda item: item[0])
            positions_in_order = [name for id, name in sorted_positions_by_id]
            self.position_filter.addItems(positions_in_order)
        
        teams = sorted(self.model['TeamName'].unique())
        self.team_filter.addItems(teams)
        
        self.position_filter.blockSignals(False)
        self.team_filter.blockSignals(False)

    def remove_all_injuries(self):
        if self.model is None:
            QMessageBox.warning(self, "No Roster Loaded", "You must load a roster before performing this action.")
            return

        reply = QMessageBox.question(self, "Confirm Action",
                                    "This will clear the active injury data for every player in the roster. "
                                    "This action cannot be undone.\n\nAre you sure you want to continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # INJY table columns are not in define.csv, so they are not renamed. use their original cryptic names.
            injury_columns_to_zero = [
                'INIR',
                'INJL',
                'INJS',
                'INJT',
                'INSI',
                'INTW',
                'TGID_injy'
            ]

            changes_made = 0
            for col in injury_columns_to_zero:
                if col in self.model.columns:
                    self.model.loc[:, col] = 0
                    changes_made += 1

            if changes_made > 0:
                self.player_editor.mark_dirty()  # Mark that there are unsaved changes
                self.status_bar.showMessage("All injuries have been cleared. Save the roster to make the changes permanent.", 5000)
                QMessageBox.information(self, "Success", "All active injury data has been reset to 0.")
            else:
                QMessageBox.information(self, "No Injury Data", "No active injury columns were found in the roster data.")

    def open_portrait_copier(self):
        if self.model is None:
            QMessageBox.warning(self, "No Roster Loaded", "You must load a destination roster first.")
            return

        dialog = PortraitCopierDialog(self.model, self.data_manager, self)
        dialog.exec()

        if self.player_editor.player_index is not None:
            self.player_editor.load_player(self.player_editor.player_index)

    def fix_logically_invalid_archetypes(self):
        if self.model is None: return

        self.status_bar.showMessage("Scanning roster for invalid archetypes...")
        QApplication.processEvents()

        position_group_map = self.data_manager.position_group_map
        players_to_fix = []

        for index, player in self.model.iterrows():
            current_archetype = player.get('Archetype', '')
            if not current_archetype or current_archetype == "Unknown": continue
            player_pos = player['PositionName']
            player_group = position_group_map.get(player_pos, player_pos)
            archetype_prefix = str(current_archetype).split('_')[0]
            if player_group != archetype_prefix:
                players_to_fix.append(index)

        if not players_to_fix:
            QMessageBox.information(self, "Scan Complete", "No players with logically invalid archetypes were found.")
            self.status_bar.showMessage("Scan complete.", 5000)
            return

        reply = QMessageBox.question(self, "Confirm Fixes",
                                    f"Found {len(players_to_fix)} players with archetypes that are invalid for their position (e.g., a WR with a HB archetype).\n\n"
                                    "This tool will automatically recalculate the BEST possible archetype for each of these players based on their current ratings.\n\n"
                                    "Do you want to continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            self.status_bar.showMessage("Operation cancelled.", 5000)
            return

        self.progress_dialog = ProgressDialog("Fixing Invalid Archetypes...", self)
        self.progress_dialog.show()

        changes_made = 0
        processed_count = 0
        inverse_archetype_map = self.data_manager.inverse_archetype_map
        failure_reasons = {'calculation_failed': [], 'id_not_found': []}

        for index in players_to_fix:
            processed_count += 1
            progress = int((processed_count / len(players_to_fix)) * 100)
            self.progress_dialog.update_progress(progress, f"Processing {processed_count}/{len(players_to_fix)}...")
            player_data = self.model.loc[index]
            new_archetype = self.archetype_calculator.calculate_best_archetype(player_data)

            if not new_archetype:
                pos_group = position_group_map.get(player_data['PositionName'], player_data['PositionName'])
                if pos_group not in failure_reasons['calculation_failed']:
                    failure_reasons['calculation_failed'].append(pos_group)
                continue

            new_id = inverse_archetype_map.get(new_archetype)
            if not new_id:
                if new_archetype not in failure_reasons['id_not_found']:
                    failure_reasons['id_not_found'].append(new_archetype)
                continue
            
            self.model.at[index, 'Archetype'] = new_archetype
            self.model.at[index, 'PLTY'] = new_id
            changes_made += 1

        self.progress_dialog.close()
        self.progress_dialog = None
        self.status_bar.showMessage(f"Fix complete. {changes_made} players were updated.", 5000)
        
        # Show a detailed final report
        report = f"Operation complete.\n\nSuccessfully updated: {changes_made} players.\nFailed to update: {len(players_to_fix) - changes_made} players."
        if failure_reasons['calculation_failed']:
            missing_groups = ", ".join(failure_reasons['calculation_failed'])
            report += f"\n\nReason: Could not calculate new archetypes for some position groups.\n"
            report += f"ACTION: Open 'archetype_breakdown.xlsx' and ensure the following groups have entries in the 'Weights' sheet: {missing_groups}"
        
        if failure_reasons['id_not_found']:
            missing_archs = ", ".join(failure_reasons['id_not_found'])
            report += f"\n\nReason: Some calculated archetypes are not in the master list.\n"
            report += f"ACTION: The following archetypes exist in your .xlsx file but are missing from 'PLTYLookup.json': {missing_archs}"

        QMessageBox.information(self, "Fix Report", report)

        if changes_made > 0:
            self.player_editor.mark_dirty()
            if self.player_editor.player_index is not None:
                self.player_editor.load_player(self.player_editor.player_index)

    def apply_filters(self):
        if self.model is None:
            return

        search_text = self.search_box.text().lower()
        selected_pos = self.position_filter.currentText()
        selected_team = self.team_filter.currentText()

        mask = pd.Series(True, index=self.model.index)

        if search_text:
            full_names = self.model['First Name'].str.cat(self.model['Last Name'], sep=' ').str.lower()
            mask &= full_names.str.contains(search_text, na=False)
        
        if selected_pos != "All Positions":
            mask &= (self.model['PositionName'] == selected_pos)
        
        if selected_team != "All Teams":
            mask &= (self.model['TeamName'] == selected_team)

        self.filtered_model_indices = self.model.index[mask]
        self.refresh_player_list()

    def refresh_player_list(self):
        self.player_list.setSortingEnabled(False)
        self.player_list.clearContents()
        self.player_editor.clear_editor()
        self.show_unmapped_button.setEnabled(False)
        self.regen_archetype_button.setEnabled(False)
        self.recalc_ovr_button.setEnabled(False)
        self.debug_player_button.setEnabled(False)

        if self.filtered_model_indices is None:
            self.player_list.setRowCount(0)
        else:
            filtered_data = self.model.loc[self.filtered_model_indices]
            self.player_list.setRowCount(len(filtered_data))
            for i, (idx, row_data) in enumerate(filtered_data.iterrows()):
                name = f"{row_data.get('First Name','')} {row_data.get('Last Name','')}"
                pos = row_data.get("PositionName", "N/A")
                overall = int(row_data.get("Overall", 0))
                age = int(row_data.get("Age", 0))
                
                name_item = QTableWidgetItem(name)
                name_item.setData(Qt.ItemDataRole.UserRole, idx) 
                
                pos_item = QTableWidgetItem(pos)
                overall_item = NumericTableWidgetItem(str(overall))
                age_item = NumericTableWidgetItem(str(age))

                # Center the text for the Position and Overall columns
                pos_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                overall_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                
                self.player_list.setItem(i, 0, name_item)
                self.player_list.setItem(i, 1, pos_item)
                self.player_list.setItem(i, 2, overall_item)
                self.player_list.setItem(i, 3, age_item)

        self.player_list.setSortingEnabled(True)
        self.player_list.sortByColumn(self.sort_column, self.sort_order)

    def on_player_selected(self, row, column):
        item = self.player_list.item(row, 0)
        if item:
            df_index = item.data(Qt.ItemDataRole.UserRole)
            if self.player_editor.load_player(df_index):
                self.show_unmapped_button.setEnabled(True)
                self.regen_archetype_button.setEnabled(True)
                self.recalc_ovr_button.setEnabled(True)
                self.debug_player_button.setEnabled(True)
            
    def debug_player_archetype(self):
        if self.player_editor.player_index is None or self.model is None:
            QMessageBox.warning(self, "No Player Selected", "Please select a player to debug.")
            return

        player_data = self.model.loc[self.player_editor.player_index]

        print("\n" + "="*50)
        print("DEBUGGING PLAYER EQUIPMENT DATA")
        print("="*50)

        equipment_fields = [
            "Towel", "JERSEYTYPE", "JerseySleeveType", "SIDELINE_HEADGEAR", "Helmet",
            "Visor", "Mouthpiece", "Facemask", "Sleeves Temp", "Eye Paint", "Flak Jacket",
            "Hand Warmer", "Neck Roll", "Sock Height", "PLYR_BREATHERITE", "PLYR_UNDERSHIRT",
            "Pad Size", "Pad Defn", "Sleeve Left", "Back Plate"
        ]

        for field in equipment_fields:
            if field in player_data:
                value = player_data[field]
                value_type = type(value).__name__
                print(f"Field: '{field}', Value: '{value}', Type: {value_type}")
            else:
                print(f"Field: '{field}' NOT FOUND in player data.")
        
        print("="*50 + "\n")

        player_name = f"{player_data.get('First Name', '')} {player_data.get('Last Name', '')}"
        player_pos = player_data.get('PositionName', 'N/A')

        current_archetype = player_data.get('Archetype', 'Not Found')
        current_id = self.data_manager.inverse_archetype_map.get(current_archetype, 'N/A')
        calculated_archetype = self.archetype_calculator.calculate_best_archetype(player_data)

        is_in_master_list = current_archetype in self.data_manager.inverse_archetype_map
        
        archetype_prefix = str(current_archetype).split('_')[0]
        
        player_position_group = self.data_manager.position_group_map.get(player_pos, player_pos)
        
        is_logically_valid = is_in_master_list and (archetype_prefix == player_position_group)
        
        is_optimal = is_logically_valid and (current_archetype == calculated_archetype)
        is_convertible = current_archetype in self.data_manager.archetype_conversion_map
        conversion_target = self.data_manager.archetype_conversion_map.get(current_archetype, "N/A")

        report = f"""
        <html><head/><body>
        <p><b>Archetype Analysis for: {player_name} ({player_pos})</b></p>
        <hr>
        <p><b><u>Data Trail:</u></b></p>
        <p>1. Current Archetype Name: <b>{current_archetype}</b></p>
        <p>2. Mapped ID in New Roster: <b>{current_id}</b></p>
        <p>3. Calculated Best Archetype: <b>{calculated_archetype or 'Calculation Failed'}</b></p>
        <hr>
        <p><b><u>Analysis:</u></b></p>
        """

        if is_in_master_list:
            report += f"<p><b>&#9989; Archetype exists in master list.</b> (The name '{current_archetype}' is in PLTYLookup.json).</p>"
        else:
            report += f"<p><b>&#10060; Archetype is INVALID.</b> (The name '{current_archetype}' was NOT found in PLTYLookup.json).</p>"

        if is_logically_valid:
            report += f"<p><b>&#9989; Archetype is LOGICALLY VALID.</b> ('{archetype_prefix}' is the correct group for a {player_pos}).</p>"
        else:
            report += f"<p><b>&#10060; Archetype is LOGICALLY INVALID.</b> A {player_pos} (group: {player_position_group}) cannot be a '{current_archetype}' (group: {archetype_prefix}). This is the main sign of a legacy roster issue.</p>"

        if not calculated_archetype:
            report += f"<p><b>&#10060; Archetype calculation FAILED.</b> Check that the '{player_position_group}' group exists in archetype_breakdown.xlsx.</p>"
        elif is_optimal:
            report += "<p><b>&#9989; Archetype is OPTIMAL.</b></p>"
        else:
            report += f"<p><b>&#10060; Archetype is NOT OPTIMAL.</b> (The best is '{calculated_archetype}').</p>"

        if is_convertible:
            report += f"<p><b>&#9989; This is a known LEGACY archetype.</b> Use the 'Convert Old Archetypes' tool to change it to <b>{conversion_target}</b>.</p>"
        else:
            if not is_logically_valid and is_in_master_list:
                report += f"<p><b><u>ACTION REQUIRED:</u> To fix this, add '<b>{current_archetype}</b>' to the `archetype_conversion_map` in DataManager to map it to a valid {player_pos} archetype.</b></p>"

        report += "</body></html>"

        QMessageBox.information(self, "Player Archetype Debug", report)

    def diagnose_save_process(self):
        if self.model is None:
            print("\nDEBUG SAVE: No roster loaded.")
            return

        print("\n" + "="*60)
        print("STARTING SAVE PROCESS DIAGNOSTIC")
        print("="*60)

        df_play = self.model.copy()

        print("\n--- CHECKPOINT 1: Initial State of 'df_play' ---")
        power_move_cols = [col for col in df_play.columns if 'power move' in str(col).lower()]
        if power_move_cols:
            print(f"Found potential 'Power Moves' columns: {power_move_cols}")
            print("Sample data (first 5 rows):")
            print(df_play[power_move_cols].head())
        else:
            print("Could not find a 'Power Moves' column in the initial DataFrame.")

        inverse_dev_trait_map = {v: k for k, v in self.data_manager.dev_trait_map.items()}
        if 'XP Rate/TraitDevelopment' in df_play.columns:
            df_play['PROL'] = df_play['XP Rate/TraitDevelopment'].map(inverse_dev_trait_map)


        print("\n--- CHECKPOINT 2: After adding ID columns (e.g., PROL) ---")
        print("No changes expected for 'Power Moves' here. Verifying...")
        print(f"Columns still present: {power_move_cols}")


        inverse_header_map = {v: k for k, v in self.data_manager.header_map.items()}
        df_play.rename(columns=inverse_header_map, inplace=True)


        print("\n--- CHECKPOINT 3: CRITICAL - After Renaming to Cryptic Headers ---")
        plpm_cols = [col for col in df_play.columns if 'plpm' in str(col).lower()]
        if len(plpm_cols) > 1:
            print(f"!!! ANOMALY DETECTED !!! Found {len(plpm_cols)} columns named 'PLPM': {plpm_cols}")
            print("This is the cause of the data loss. One of these columns is being dropped.")
            print("ACTION: Find which readable names in define.csv are being renamed to PLPM.")
        elif plpm_cols:
            print(f"Successfully found one 'PLPM' column: {plpm_cols}")
        else:
            print("!!! ERROR !!! The 'Power Moves' column was lost during the rename operation.")


        df_play_deduped = df_play.loc[:,~df_play.columns.duplicated()]

        print("\n--- CHECKPOINT 4: Final State After Dropping Duplicates ---")
        final_plpm_cols = [col for col in df_play_deduped.columns if 'plpm' in str(col).lower()]
        if final_plpm_cols:
            print(f"The 'PLPM' column survived. Final columns: {final_plpm_cols}")
            print("If the data is still wrong, the wrong column may have been kept.")
        else:
            print("!!! ERROR !!! The 'PLPM' column was dropped by the de-duplication step.")

        print("\n" + "="*60)
        print("DIAGNOSTIC COMPLETE")
        print("="*60)
        QMessageBox.information(self, "Diagnostic Complete", "Detailed report has been printed to the console/terminal.")

    def show_uncategorized_fields(self):
        if self.model is None:
            QMessageBox.warning(self, "No Roster Loaded", "Please load a roster first.")
            return

        # 1. Get all columns that were successfully loaded into the DataFrame.
        all_loaded_columns = set(self.model.columns)

        # 2. Get all columns that are defined in the UI layout file.
        categorized_columns = self.player_editor.get_categorized_attributes()

        # 3. Find the difference.
        uncategorized_columns = sorted(list(all_loaded_columns - categorized_columns))

        # 4. Display the report.
        if not uncategorized_columns:
            QMessageBox.information(self, "Scan Complete", "All loaded data fields are successfully categorized in your ui_layout.json.")
            return

        report = "The following data fields were loaded successfully but are not defined in your 'config/ui_layout.json' file.\n\n"
        report += "They will appear in the 'Advanced -> Uncategorized' section.\n\n"
        report += "To fix this, check for:\n"
        report += "1. Typos or mismatches between these names and the names in your JSON file.\n"
        report += "2. A syntax error in your JSON file that caused the application to load its fallback layout.\n\n"
        report += "--------------------------------\n"
        report += "\n".join(uncategorized_columns)

        dialog = QDialog(self)
        dialog.setWindowTitle("Uncategorized Fields Report")
        layout = QVBoxLayout(dialog)
        text_area = QScrollArea()
        text_area.setWidgetResizable(True)
        label = QLabel(report)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_area.setWidget(label)
        layout.addWidget(text_area)
        dialog.resize(500, 600)
        dialog.exec()

    def reset_filters(self):
        self.search_box.clear()
        self.position_filter.setCurrentIndex(0)
        self.team_filter.setCurrentIndex(0)

    def set_window_dirty_status(self, is_dirty):
        title = self.base_title
        if is_dirty:
            self.setWindowTitle(f"{title}*")
        else:
            self.setWindowTitle(title)

    def closeEvent(self, event):
        if self.player_editor.is_dirty:
            reply = QMessageBox.question(self, 'Unsaved Changes',
                                       'You have unsaved changes. Do you want to save them before exiting?',
                                       QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                event.ignore()
                QMessageBox.information(self, "Save First", "Please use the 'Save Roster' button before exiting.")
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
        
        self.worker_thread.quit()
        self.worker_thread.wait()

class RawDataDialog(QDialog):
    def __init__(self, unmapped_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unmapped Player Data")
        self.resize(500, 600)
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel("This table shows all data for the selected player that is not currently mapped in define.csv.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Cryptic Field", "Value"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        if unmapped_data:
            sorted_items = sorted(unmapped_data.items())
            self.table.setRowCount(len(sorted_items))
            for row, (field, value) in enumerate(sorted_items):
                self.table.setItem(row, 0, QTableWidgetItem(str(field)))
                self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    import qdarkstyle
    from qdarkstyle.dark.palette import DarkPalette
    dark_stylesheet = qdarkstyle.load_stylesheet(palette=DarkPalette)
    app.setStyleSheet(dark_stylesheet)
    editor = RosterEditor()
    editor.show()
    sys.exit(app.exec())