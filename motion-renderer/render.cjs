const path=require('node:path');
const fs=require('node:fs');
const {bundle}=require('@remotion/bundler');
const {selectComposition,renderMedia,renderStill}=require('@remotion/renderer');
async function main(){
 const work=path.resolve(process.argv[2]);
 const plan=JSON.parse(fs.readFileSync(path.join(work,'motion-plan.json'),'utf8'));
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'src/index.tsx'),publicDir:path.join(work,'motion-assets'),outDir:path.join(work,'motion-bundle')});
 const inputProps={plan};
 const browserExecutable=process.env.REMOTION_BROWSER_EXECUTABLE || undefined;
 const composition=await selectComposition({serveUrl,id:'LessonPromo',inputProps,browserExecutable});
 // Bound decoder workers on desktop machines shared with the lesson pipeline.
 const videoOptions={offthreadVideoThreads:1,offthreadVideoCacheSizeInBytes:256*1024*1024};
 await renderMedia({serveUrl,composition,inputProps,browserExecutable,...videoOptions,codec:'h264',outputLocation:path.join(work,'motion-silent.mp4'),concurrency:1,crf:20});
 for(let i=0;i<plan.shots.length;i++){
   const s=plan.shots[i];
   await renderStill({serveUrl,composition,inputProps,browserExecutable,...videoOptions,frame:s.from+Math.min(s.frames-1,Math.max(12,Math.floor(s.frames*.5))),output:path.join(work,`motion-scene-${i+1}.jpg`),imageFormat:'jpeg'});
 }
 console.log('Motion render complete');
}
main().catch(e=>{console.error(e.message);process.exit(1)});
