import fs from 'node:fs';
import {occupancyReport} from '../static/joint_occupancy.js';
const data=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(data).map(([key,d])=>[key,occupancyReport(d)]))));
