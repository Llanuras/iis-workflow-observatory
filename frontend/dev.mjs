// Vite decodes its HTML root as a URL. A '%' in a parent directory breaks that
// conversion. A temporary symlink keeps the course directory intact.
import { mkdtempSync, symlinkSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
const original = dirname(fileURLToPath(import.meta.url));
const temporary = mkdtempSync(join(tmpdir(), 'iis-vite-'));
const root = join(temporary, 'frontend');
symlinkSync(original, root, 'dir');
const server = await createServer({ configFile:false, root,
  plugins:[react(),tailwindcss()], resolve:{preserveSymlinks:true},
  server:{host:'127.0.0.1',port:5173,proxy:{'/api':'http://127.0.0.1:8000'},fs:{allow:[original,temporary]}} });
await server.listen();
server.printUrls();
async function close(){await server.close();unlinkSync(root);rmdirSync(temporary);process.exit(0)}
process.on('SIGINT',close);process.on('SIGTERM',close);
