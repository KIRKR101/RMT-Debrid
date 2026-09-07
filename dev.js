import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const venvPython = process.platform === 'win32'
	? ['.venv/Scripts/python.exe', 'venv/Scripts/python.exe']
	: ['.venv/bin/python', 'venv/bin/python'];
const command = process.env.PYTHON_BIN || venvPython.find((candidate) => existsSync(candidate)) || (process.platform === 'win32' ? 'py' : 'python3');
const backendArgs = process.argv.slice(2).length ? process.argv.slice(2) : ['main.py'];
const args = command === 'py' ? ['-3', ...backendArgs] : backendArgs;

const backend = spawn(command, args, {
	stdio: 'inherit',
	env: { ...process.env, RELOAD: process.env.RELOAD ?? 'true' }
});
const frontend = spawn(process.execPath, ['vite', 'dev'], {
	cwd: 'frontend',
	stdio: 'inherit'
});

let shuttingDown = false;
function shutdown(signal) {
	if (shuttingDown) return;
	shuttingDown = true;
	backend.kill(signal);
	frontend.kill(signal);
}

for (const signal of ['SIGINT', 'SIGTERM']) {
	process.on(signal, () => shutdown(signal));
}

function onChildError(name, child) {
	child.on('error', (error) => {
		console.error(`Could not start ${name}: ${error.message}`);
		shutdown('SIGTERM');
		process.exitCode = 1;
	});
}

onChildError(command, backend);
onChildError('frontend dev server', frontend);

backend.on('exit', (code, signal) => {
	if (signal) frontend.kill(signal);
	else frontend.kill();
	if (!shuttingDown) process.exit(code ?? 1);
});

frontend.on('exit', (code, signal) => {
	if (signal) backend.kill(signal);
	else backend.kill();
	if (!shuttingDown) process.exit(code ?? 1);
});
