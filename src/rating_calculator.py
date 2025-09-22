import re
import pandas as pd
import ast


def safe_min(*args):
    return min(args)

def safe_max(*args):
    return max(args)

SAFE_FUNCTIONS = {
    'MIN': safe_min,
    'MAX': safe_max,
}

class RatingCalculator:

    def __init__(self, formula_file, header_map):
        self.formulas = {}
        self.header_map = header_map
        self.inverse_header_map = {v: k for k, v in header_map.items()}
        self._load_formulas_from_txt(formula_file)

    def _translate_excel_to_python(self, formula):

        formula = re.sub(r'([A-Z]+)\d+', r'\1', formula)
        

        formula = re.sub(r'\bC\b', 'Archetype', formula)
        for readable, cryptic in self.inverse_header_map.items():
            formula = re.sub(r'\b' + cryptic + r'\b', readable, formula)


        if formula.startswith("=PRODUCT("):
            formula = formula[9:-1]


        formula = re.sub(r'IF\((.*?),\s*(.*?),\s*(.*?)\)', r'(\2 if \1 else \3)', formula)


        def or_replacer(match):
            conditions = match.group(1).split(',')
            return '(' + ' or '.join(cond.strip() for cond in conditions) + ')'
        formula = re.sub(r'OR\((.*?)\)', or_replacer, formula)


        formula = re.sub(r'(\w+)\s*=\s*(".*?")', r'\1 == \2', formula)


        return formula.lstrip('=')

    def _load_formulas_from_txt(self, file_path):
        """Parses the custom formula text file."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Warning: Formula file not found at {file_path}")
            return


        position_sections = re.split(r'\n([A-Za-z\s]+)\n\n', content)
        

        for i in range(1, len(position_sections), 2):
            pos_name = position_sections[i].strip()
            pos_formulas_text = position_sections[i+1]
            

            pos_map = {
                'Quarterbacks': 'QB', 'Halfback': 'HB', 'Wide Receiver': 'WR',
                'Tight End': 'TE', 'Defensive Linemen': 'DE', 'Linebackers': 'LB',
                'Cornerbacks': 'CB', 'Safeties': 'SS'
            }
            pos_key = pos_map.get(pos_name, pos_name)
            self.formulas[pos_key] = {}

            rating_matches = re.findall(r'([A-Za-z\s]+)\n\n\s*=(.*)', pos_formulas_text)
            for rating_name, formula in rating_matches:
                clean_rating_name = rating_name.strip().title().replace(" ", "")
                python_formula = self._translate_excel_to_python(formula)
                self.formulas[pos_key][clean_rating_name] = python_formula

    def _evaluate_formula(self, formula, player_data):
        eval_context = {**player_data, **SAFE_FUNCTIONS}
        try:
            result = eval(formula, {"__builtins__": {}}, eval_context)
            return round(max(10, min(99, result)))
        except Exception as e:
            print(f"Error evaluating formula '{formula}': {e}")
            return player_data.get(formula, 0) 

    def calculate_all_ratings(self, player_data):
        position = player_data.get('PositionName', 'Unknown')
        
        if 'LB' in position: position = 'LB'
        if 'S' in position: position = 'SS'

        pos_formulas = self.formulas.get(position)
        if not pos_formulas:
            return {}

        new_ratings = {}
        numeric_player_data = {k: pd.to_numeric(v, errors='coerce') for k, v in player_data.items()}
        numeric_player_data['Archetype'] = player_data.get('Archetype')

        for rating_name, formula in pos_formulas.items():
            new_ratings[rating_name] = self._evaluate_formula(formula, numeric_player_data)
        
        return new_ratings