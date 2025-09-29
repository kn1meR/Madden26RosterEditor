const MaddenRosterHelper = require('madden-file-tools/helpers/MaddenRosterHelper');
const fs = require('fs');
const path = require('path');

const DEBUG_WRITE_FILES = false; 
const DEBUG_OUTPUT_DIR = 'debug_output';

function findTableByName(file, tableName) {
    if (!file || !file._tables) return null;
    return file._tables.find(table => table.name === tableName);
}

function simplifyRecord(record) {
    const simpleFields = {};
    if (!record) return simpleFields;

    // 1. Read from the base fields
    if (record._fields) {
        for (const key in record._fields) {
            const value = record._fields[key].value;
            if (typeof value !== 'object' || value === null) {
                simpleFields[key] = value;
            }
        }
    }

    // 2. Read from CharacterVisuals
    if (record.CharacterVisuals && record.CharacterVisuals._fields) {
        for (const key in record.CharacterVisuals._fields) {
            const value = record.CharacterVisuals._fields[key].value;
            if (typeof value !== 'object' || value === null) {
                simpleFields[key] = value;
            }
        }
    }

    // 3. (THE FIX) Read from PlayerRatings - This is likely where PLPM is.
    if (record.PlayerRatings && record.PlayerRatings._fields) {
        for (const key in record.PlayerRatings._fields) {
            const value = record.PlayerRatings._fields[key].value;
            if (typeof value !== 'object' || value === null) {
                simpleFields[key] = value;
            }
        }
    }
    
    return simpleFields;
}

function readRoster(filePath) {
    // This function does not need changes, as it uses the now-fixed simplifyRecord helper.
    if (!fs.existsSync(filePath)) {
        console.error(`Error reading roster: Input file not found: ${filePath}`);
        process.exit(1);
    }

    const helper = new MaddenRosterHelper();
    const tablesToRead = ['PLAY', 'PSAL', 'INJY', 'TEAM', 'DCHT', 'BLOB'];
    const output = {};

    helper.load(filePath)
        .then(file => {
            if (DEBUG_WRITE_FILES) {
                if (!fs.existsSync(DEBUG_OUTPUT_DIR)) fs.mkdirSync(DEBUG_OUTPUT_DIR);
                console.error(`DEBUG: Writing table data to '${DEBUG_OUTPUT_DIR}'...`);
            }

            tablesToRead.forEach(tableName => {
                const table = findTableByName(file, tableName);
                if (table && table.records) {
                    const simplifiedRecords = table.records.map(simplifyRecord);
                    const key = tableName.toLowerCase(); 
                    output[key] = simplifiedRecords;

                    if (DEBUG_WRITE_FILES) {
                        const debugFilePath = path.join(DEBUG_OUTPUT_DIR, `${tableName}_data.json`);
                        const jsonContent = JSON.stringify(simplifiedRecords, null, 2);
                        fs.writeFileSync(debugFilePath, jsonContent);
                        console.error(` -> Successfully wrote ${tableName} data.`);
                    }
                }
            });
            
            console.log(JSON.stringify(output));
        })
        .catch(error => {
            console.error(`Error reading roster: ${error.message}`);
            process.exit(1);
        });
}

async function writeRoster(originalFilePath, newFilePath) {
    if (!fs.existsSync(originalFilePath)) {
        console.error(`Error writing roster: Original file not found: ${originalFilePath}`);
        process.exit(1);
    }
    const helper = new MaddenRosterHelper();
    try {
        const stdinData = await readStdin();
        const incomingData = JSON.parse(stdinData);

        await helper.load(originalFilePath);

        for (const key in incomingData) {
            const tableName = key.toUpperCase();
            const table = findTableByName(helper.file, tableName);
            const newRecords = incomingData[key];

            if (table) {
                newRecords.forEach((newRecord, index) => {
                    const recordToUpdate = table.records[index];
                    if (recordToUpdate) {
                        for (const fieldKey in newRecord) {
                            if (recordToUpdate._fields[fieldKey]) {
                                recordToUpdate._fields[fieldKey].value = newRecord[fieldKey];
                            }
                            else if (recordToUpdate.CharacterVisuals && recordToUpdate.CharacterVisuals._fields[fieldKey]) {
                                recordToUpdate.CharacterVisuals._fields[fieldKey].value = newRecord[fieldKey];
                            }
                            // Also check in Career - This is where PLDT is located.
                            else if (recordToUpdate.Career && recordToUpdate.Career._fields[fieldKey]) {
                                recordToUpdate.Career._fields[fieldKey].value = newRecord[fieldKey];
                            }
                            else if (recordToUpdate.PlayerRatings && recordToUpdate.PlayerRatings._fields[fieldKey]) {
                                recordToUpdate.PlayerRatings._fields[fieldKey].value = newRecord[fieldKey];
                            }
                        }
                    }
                });
            }
        }

        await helper.save(newFilePath);
        console.log("Roster saved successfully.");
    } catch (error) {
        console.error(`Error writing roster: ${error.message}`);
        process.exit(1);
    }
}

function readStdin() { return new Promise((resolve, reject) => { let data = ''; process.stdin.setEncoding('utf8'); process.stdin.on('readable', () => { let chunk; while ((chunk = process.stdin.read()) !== null) { data += chunk; } }); process.stdin.on('end', () => { resolve(data); }); process.stdin.on('error', reject); }); }
const args = process.argv.slice(2);
const command = args[0];
if (command === 'read') { readRoster(args[1]); }
else if (command === 'write') { writeRoster(args[1], args[2]); }
else { console.error(`Unknown command: '${command}'. Use 'read' or 'write'.`); }
