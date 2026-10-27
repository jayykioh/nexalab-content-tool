// Read-only snapshot for video mapping. Requires the sibling BE generated Prisma client.
const fs = require('node:fs');
const path = require('node:path');

const projectRoot = path.resolve(__dirname, '..', '..');
const backend = path.join(projectRoot, 'BE-NexaLab');
require(path.join(backend, 'node_modules', 'dotenv')).config({ path: path.join(backend, '.env'), quiet: true });
const { PrismaClient } = require(path.join(backend, 'node_modules', '@prisma', 'client'));
const prisma = new PrismaClient();
const output = path.resolve(__dirname, '..', 'data', 'full-p2-crawl');

async function main() {
  const columns = await prisma.$queryRaw`
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'Lesson'
  `;
  const hasSgkReference = columns.some((column) => column.column_name === 'sgkReference');
  const nine = await prisma.lesson.findMany({
    where: { grade: 9, id: { startsWith: 'pack-khtn9-l' } },
    select: { id: true, title: true, subjectId: true, curriculumChapterCode: true, curriculumTopicCode: true,
      ...(hasSgkReference ? { sgkReference: true } : {}),
      status: true, scope: true, videos: true, sections: true, review: true,
      steps: { where: { type: 'VIDEO' }, select: { id: true, position: true, config: true } } },
    orderBy: { id: 'asc' },
  });
  const eight = await prisma.lesson.findMany({
    where: { grade: 8 },
    select: { id: true, title: true, subjectId: true, curriculumChapterCode: true, curriculumTopicCode: true,
      curriculumOrder: true, status: true, scope: true, videos: true, sections: true,
      steps: { where: { type: 'VIDEO' }, select: { id: true, position: true, config: true } } },
    orderBy: { id: 'asc' },
  });
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'khtn9-db-baseline.json'), JSON.stringify({
    kind: 'read-only-db-baseline', capturedAt: new Date().toISOString(), lessons: nine,
    videoLessons: nine.filter(x => Array.isArray(x.videos) && x.videos.length).length,
    sgkReferenceColumnState: hasSgkReference ? 'PRESENT' : 'MISSING_MIGRATION_NOT_APPLIED',
    sgkReferenceLessons: hasSgkReference ? nine.filter(x => x.sgkReference !== null).length : null,
    videoCount: nine.reduce((n, x) => n + (Array.isArray(x.videos) ? x.videos.length : 0) +
      (Array.isArray(x.sections) ? x.sections.reduce((m, s) => m + (s.videos?.length || 0), 0) : 0), 0),
  }, null, 2) + '\n');
  fs.writeFileSync(path.join(output, 'khtn8-db-baseline.json'), JSON.stringify({
    kind: 'read-only-db-baseline', capturedAt: new Date().toISOString(), lessons: eight,
  }, null, 2) + '\n');
  console.log(JSON.stringify({ grade9Lessons: nine.length, grade9VideoLessons: nine.filter(x => Array.isArray(x.videos) && x.videos.length).length,
    sgkReferenceColumnState: hasSgkReference ? 'PRESENT' : 'MISSING_MIGRATION_NOT_APPLIED',
    grade8Lessons: eight.length }));
}

main().finally(() => prisma.$disconnect());
