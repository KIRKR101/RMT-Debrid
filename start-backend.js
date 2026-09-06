import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const venvPython = process.platform === 'win32'
	? ['.venv/Scripts/python.exe', 'venv/Scripts/python.exe']
	: ['.venv/bin/python', 'venv/bin/python'];
const command = process.env.PYTHON_BIN || venvPython.find((candidate) => existsSync(candidate)) || (process.platform === 'win32' ? 'py' : 'python3');
const requestedArgs = process.argv.slice(2);
const buildFrontend = requestedArgs.includes('--build-frontend');
const backendArgs = requestedArgs.filter((arg) => arg !== '--build-frontend');
if (buildFrontend) {
	const build = spawnSync(process.execPath, ['vite', 'build'], { cwd: 'frontend', stdio: 'inherit' });
	if (build.status !== 0) process.exit(build.status ?? 1);
}
const args = requestedArgs.length ? requestedArgs : ['main.py'];
args.splice(0, args.length, ...(backendArgs.length ? backendArgs : ['main.py']));
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
