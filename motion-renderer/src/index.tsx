import React from 'react';
import {AbsoluteFill, Composition, Img, OffthreadVideo, Sequence, interpolate, registerRoot, spring, staticFile, useCurrentFrame} from 'remotion';

type Shot = {from:number;frames:number;clip:string;text:string;label:string;role:'hook'|'detail'|'cta';focus?:{x:number;y:number;width:number;height:number;from:number;to:number}};
type Plan = {platform?:string;frames:number;company:string;cta:string;logo?:string;source_aspect?:number;shots:Shot[]};
const clamp = {extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const ink='#171330', lime='#D8FF52', purple='#7346FF', coral='#FF806C';
const font='Segoe UI, Arial, sans-serif';

const Captions:React.FC<{shot:Shot}>=({shot})=>{
  const f=useCurrentFrame(); const words=shot.text.split(/\s+/);
  const groups:string[]=[];let buffer='';
  for(const word of words){if(buffer && (buffer+' '+word).length>30){groups.push(buffer);buffer='';}buffer+=(buffer?' ':'')+word;}if(buffer)groups.push(buffer);
  const index=Math.min(groups.length-1,Math.floor(f/shot.frames*groups.length));
  const start=index*shot.frames/groups.length;
  return <div style={{position:'absolute',left:70,right:110,top:1400,textAlign:'center',fontSize:54,fontWeight:750,lineHeight:1.2,color:'white',transform:`translateY(${interpolate(f-start,[0,5],[12,0],clamp)}px)`}}>
    <div style={{display:'inline-block',background:ink,padding:'16px 24px',borderRadius:14,lineHeight:1.25}}>{groups[index]}</div>
  </div>;
};

const Scene:React.FC<{shot:Shot;plan:Plan;index:number}>=({shot,plan,index})=>{
  const f=useCurrentFrame();const expressive=plan.platform==='reels' || !plan.platform || plan.platform==='generic';const guided=plan.platform==='vk';const motion=expressive?1:guided?.3:.08;const entrance=spring({frame:f,fps:30,config:{damping:19,stiffness:150}});
  const progress=f/Math.max(1,shot.frames-1);
  const accent=shot.role==='hook'?lime:shot.role==='cta'?coral:lime;
  const isCta=shot.role==='cta';
  // Focus is only supplied from a verified source annotation; no invented UI.
  const focus=shot.focus;
  const zoom=focus?interpolate(f,[focus.from-8,focus.from,Math.max(focus.from+1,focus.to),Math.max(focus.from+2,focus.to+8)],[1,1.4,1.4,1],clamp):1+progress*(expressive?.08:.025);
  const screenTop=expressive?610:540; const screenHeight=Math.min(600,928/(plan.source_aspect || 1.92));
  const videoWidth=Math.min(928,screenHeight*(plan.source_aspect || 1.92));
  return <AbsoluteFill style={{background:shot.role==='detail'?'#EEE9FF':purple,color:shot.role==='detail'?ink:'white',fontFamily:font,overflow:'hidden'}}>
    <AbsoluteFill style={{background:`radial-gradient(ellipse at ${20+progress*50}% 30%, ${shot.role==='detail'?'#D8CAFF':'#A987FF'}, transparent 65%)`}}/>
    <div style={{position:'absolute',width:900,height:900,right:-620,top:500,border:`90px solid ${accent}`,borderRadius:'50%',transform:`translateY(${-progress*90}px)`,opacity:.4}}/>
    <div style={{position:'absolute',left:65,top:125,display:'flex',alignItems:'center',gap:22,fontSize:28,fontWeight:700,letterSpacing:2}}>
      {plan.logo && <Img src={staticFile(plan.logo)} style={{width:90,height:60,objectFit:'contain'}}/>}{plan.company || 'ВИДЕОИНСТРУКЦИЯ'}
    </div>
    <div style={{position:'absolute',left:65,top:225,fontSize:27,fontWeight:800,letterSpacing:3,opacity:entrance}}>{shot.role==='hook'?'РАЗБИРАЕМ НА ПРАКТИКЕ':isCta?'СМОТРИТЕ ПОЛНЫЙ УРОК':`ШАГ ${index} · НА ЭКРАНЕ`}</div>
    <div style={{position:'absolute',left:60,right:100,top:295,fontSize:shot.label.length>28?62:76,fontWeight:900,lineHeight:1.06,letterSpacing:-2,overflowWrap:'anywhere',transform:`translateY(${(1-entrance)*80*motion}px)`,opacity:entrance}}>{shot.label}
      <div style={{width:360*entrance,height:15,background:accent,marginTop:28,transform:'rotate(-2deg)'}}/>
    </div>
    <div style={{position:'absolute',left:48,right:80,top:screenTop-45,height:screenHeight+92,borderRadius:32,background:ink,padding:12,boxShadow:'0 35px 70px #1B073966',transform:`translateX(${(1-entrance)*(index%2?-850:850)*motion}px) rotate(${(1-entrance)*-5*motion}deg)`}}>
      <div style={{height:33,display:'flex',alignItems:'center',gap:8,paddingLeft:12}}>{[coral,lime,'#AA98EE'].map(c=><div key={c} style={{width:10,height:10,borderRadius:10,background:c}}/>)}<span style={{marginLeft:12,color:'#B6ABCE',fontSize:17}}>ИЗ ИСХОДНОГО УРОКА</span></div>
      <div style={{height:screenHeight,overflow:'hidden',borderRadius:18,position:'relative',background:'white'}}>
        <div style={{position:'absolute',top:0,bottom:0,left:(928-videoWidth)/2,width:videoWidth,transform:`scale(${zoom})`,transformOrigin:focus?`${focus.x*100}% ${focus.y*100}%`:'50% 50%'}}>
          <OffthreadVideo src={staticFile(shot.clip)} muted style={{width:'100%',height:'100%',objectFit:'contain'}}/>
          {focus && f>=focus.from && f<focus.to && <div style={{position:'absolute',left:`${Math.max(0,focus.x-.025)*100}%`,top:`${Math.max(0,focus.y-.035)*100}%`,width:`${Math.max(.07,focus.width)*100}%`,height:`${Math.max(.06,focus.height)*100}%`,border:`${4/zoom}px solid #FF522D`,borderRadius:8,boxShadow:'0 0 0 3px #fff9'}}/>}
        </div>
      </div>
    </div>
    {expressive && <div style={{position:'absolute',right:95,top:1170,width:90,height:90,background:accent,color:ink,borderRadius:25,fontSize:60,fontWeight:900,textAlign:'center',transform:`rotate(-12deg) scale(${spring({frame:f-8,fps:30,config:{damping:12}})})`}}>{isCta?'↗':focus?'⌖':'↓'}</div>}
    <div style={{position:'absolute',left:65,right:110,top:1300,height:7,background:shot.role==='detail'?'#CFC2ED':'#ffffff30',borderRadius:8}}><div style={{height:'100%',width:`${progress*100}%`,background:accent,borderRadius:8}}/></div>
    <Captions shot={shot}/>
    {isCta && <div style={{position:'absolute',left:65,right:110,top:1550,padding:'25px 32px',background:lime,color:ink,borderRadius:22,fontSize:35,fontWeight:850,transform:`translateY(${(1-entrance)*70}px)`}}>{plan.cta} <span style={{float:'right'}}>↗</span></div>}
    <div style={{position:'absolute',left:65,bottom:130,display:'flex',gap:12}}>{plan.shots.map((s,i)=><div key={i} style={{width:i===index?95:30,height:8,borderRadius:10,background:i===index?accent:'#9885B9'}}/>)}</div>
    {expressive && <div style={{position:'absolute',inset:0,background:accent,transform:`translateX(${interpolate(f,[0,7],[0,110],clamp)}%)`,pointerEvents:'none'}}/>}
  </AbsoluteFill>;
};
const Promo:React.FC<{plan:Plan}>=({plan})=><AbsoluteFill>{plan.shots.map((s,i)=><Sequence key={i} from={s.from} durationInFrames={s.frames}><Scene shot={s} plan={plan} index={i}/></Sequence>)}</AbsoluteFill>;
const Root=()=> <Composition id="LessonPromo" component={Promo} width={1080} height={1920} fps={30} durationInFrames={300} defaultProps={{plan:{frames:300,company:'',cta:'',shots:[]}}} calculateMetadata={({props})=>({durationInFrames:props.plan.frames})}/>;
registerRoot(Root);
