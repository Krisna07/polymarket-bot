import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const projectRoot = process.cwd();
const isWindows = process.platform === 'win32';

const venvPython = isWindows
  ? join(projectRoot, '.venv', 'Scripts', 'python.exe')
  : join(projectRoot, '.venv', 'bin', 'python');

const pythonCommand = existsSync(venvPython) ? venvPython : 'python';
const npmCommand = isWindows ? 'npm.cmd' : 'npm';
const dockerCommand = isWindows ? 'docker.exe' : 'docker';

const commands = [
  {
    name: 'backend',
    command: `"${pythonCommand}" -m uvicorn backend.app.main:app --reload --port 8000`,
  },
  {
    name: 'worker',
    command: `"${pythonCommand}" -m workers.scheduler`,
  },
  {
    name: 'frontend',
    command: `${npmCommand} --prefix frontend run dev`,
  },
];

const children = [];
let shuttingDown = false;
let exitCode = 0;

function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      shell: false,
      stdio: 'inherit',
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(' ')} exited with code ${code}`));
      }
    });
  });
}

async function ensureDockerServices() {
  if (process.env.SKIP_DOCKER === '1') {
    console.log('[setup] skipping docker startup because SKIP_DOCKER=1');
    return;
  }

  console.log('[setup] starting required docker services: postgres, redis');
  await runCommand(dockerCommand, ['compose', 'up', '-d', 'postgres', 'redis']);
}

function stopAll() {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill();
    }
  }
}

async function main() {
  try {
    await ensureDockerServices();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[setup] failed to start docker dependencies: ${message}`);
    console.error('[setup] ensure Docker Desktop is running, or set SKIP_DOCKER=1 to bypass');
    process.exit(1);
  }

  console.log('[setup] open http://localhost:5173 and connect your wallet in browser (MetaMask/Injected)');

  for (const definition of commands) {
    const child = spawn(definition.command, {
      cwd: projectRoot,
      shell: true,
      stdio: 'inherit',
    });

    child.on('error', (error) => {
      console.error(`[${definition.name}] failed to start: ${error.message}`);
      exitCode = 1;
      stopAll();
    });

    child.on('exit', (code, signal) => {
      if (shuttingDown) {
        return;
      }

      if (signal) {
        console.error(`[${definition.name}] exited from signal ${signal}`);
        exitCode = 1;
      } else if (code && code !== 0) {
        console.error(`[${definition.name}] exited with code ${code}`);
        exitCode = code;
      }

      stopAll();
    });

    children.push(child);
  }
}

process.on('SIGINT', () => {
  stopAll();
});

process.on('SIGTERM', () => {
  stopAll();
});

process.on('exit', () => {
  stopAll();
});

main()
  .then(() => Promise.all(children.map((child) => new Promise((resolve) => child.on('close', resolve)))))
  .then(() => {
    process.exit(exitCode);
  });