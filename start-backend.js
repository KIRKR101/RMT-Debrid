import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const venvPython = process.platform === 'win32'
	? ['.venv/Scripts/python.exe', 'venv/Scripts/python.exe']
	: ['.venv/bin/python', 'venv/bin/python'];
const command = process.env.PYTHON_BIN || venvPython.find((candidate) => existsSync(candidate)) || (process.platform === 'win32' ? 'py' : 'python3');
const requestedArgs = process.argv.slice(2);
const args = requestedArgs.length ? requestedArgs : ['main.py'];
if (command === 'py') args.unshift('-3');
const child = spawn(command, args, { stdio: 'inherit' });

child.on('error', (error) => {
	console.error(`Could not start ${command}: ${error.message}`);
	process.exit(1);
});

child.on('exit', (code, signal) => {
	if (signal) process.kill(process.pid, signal);
	process.exit(code ?? 1);
});
