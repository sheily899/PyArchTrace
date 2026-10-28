import { pathToFileURL } from 'node:url';

const [modulePath] = process.argv.slice(2);
if (!modulePath) throw new Error('Missing ELKJS module path');
const input = JSON.parse(await new Promise((resolve, reject) => {
  let data = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { data += chunk; });
  process.stdin.on('end', () => resolve(data));
  process.stdin.on('error', reject);
}));
const imported = await import(pathToFileURL(modulePath).href);
const ELK = imported.default?.default ?? imported.default ?? imported.ELK;
if (typeof ELK !== 'function') throw new Error('ELKJS constructor not found');
const elk = new ELK();
const graph = {
  id: 'diagram',
  layoutOptions: {
    'elk.algorithm': 'layered',
    'elk.direction': input.direction === 'TB' ? 'DOWN' : 'RIGHT',
    'elk.edgeRouting': 'ORTHOGONAL',
    'elk.layered.unnecessaryBendpoints': 'false',
    'elk.layered.spacing.nodeNodeBetweenLayers': '92',
    'elk.spacing.nodeNode': '42',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  },
  children: input.nodes.map(node => ({ id: node.id, width: node.width, height: node.height })),
  edges: input.edges.map(edge => ({ id: edge.id, sources: [edge.from], targets: [edge.to] })),
};
const laidOut = await elk.layout(graph);
process.stdout.write(JSON.stringify(laidOut));
