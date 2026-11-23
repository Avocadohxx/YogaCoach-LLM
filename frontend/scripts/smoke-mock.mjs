import { spawn } from 'node:child_process';
import { once } from 'node:events';
const env = {
  ...process.env,
  MOCK_PORT: '18001',
  BACKEND_URL: 'http://127.0.0.1:18001',
};
const server = spawn(process.execPath, ['scripts/mock-backend.mjs'], {
  env,
  stdio: ['ignore', 'pipe', 'inherit'],
  windowsHide: true,
});
const timer = setTimeout(() => server.kill(), 30000);
try {
  await Promise.race([
    once(server.stdout, 'data'),
    once(server, 'exit').then(() => {
      throw new Error('Mock failed to start');
    }),
  ]);
  const client = spawn(process.execPath, ['scripts/check-integration.mjs'], {
    env,
    stdio: 'inherit',
    windowsHide: true,
  });
  const [code] = await once(client, 'exit');
  if (code !== 0) process.exitCode = 1;
} finally {
  clearTimeout(timer);
  server.kill();
}
