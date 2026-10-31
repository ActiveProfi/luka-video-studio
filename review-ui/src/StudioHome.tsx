import { useState } from 'react';
import { API, type JobInfo } from './api';
import './StudioHome.css';
import LukaEyes from './LukaEyes';

export type StudioView = 'home' | 'projects' | 'promotion' | 'workspace' | 'new';
export function StudioIcon({name}:{name:string}) {
  const paths:Record<string,string>={home:'M3 10 12 3l9 7v11h-6v-7H9v7H3Z',projects:'M3 5h7l2 3h9v12H3Z',promotion:'m4 10 14-6v16L4 14Zm0 4 2 7h4l-2-6M21 9v6',plus:'M12 5v14M5 12h14',play:'m9 5 11 7-11 7Z',arrow:'M4 12h16m-6-6 6 6-6 6',film:'M3 4h18v16H3ZM7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4',search:'m20 20-4.5-4.5M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z'};
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.film}/></svg>;
}
export function StudioNav({view,onNavigate}:{view:StudioView;onNavigate:(v:StudioView)=>void}) {
  return <aside className="studio-rail"><button className="studio-brand" onClick={()=>onNavigate('home')} aria-label="Luka — главная"><LukaEyes/><span>Luka<small>ДЛЯ АВТОРОВ</small></span></button>
    <button className="rail-create" onClick={()=>onNavigate('new')} title="Новый видеоурок"><StudioIcon name="plus"/><span>Создать видео</span></button>
    <nav aria-label="Разделы приложения">{([['home','Главная','home'],['projects','Мои проекты','projects'],['promotion','Продвижение','promotion']] as const).map(([id,label,icon])=><button key={id} className={view===id?'selected':''} aria-current={view===id?'page':undefined} onClick={()=>onNavigate(id)} title={label}><StudioIcon name={icon}/><span>{label}</span></button>)}</nav>
    <div className="rail-note"><span className="local-dot"/><span>Локальная студия<small>Проекты на этом компьютере</small></span></div>
  </aside>;
}
function projectDate(id:string) {const m=id.match(/job_(\d{4})(\d{2})(\d{2})/);return m ? `${m[3]}.${m[2]}.${m[1]}` : 'Сохранённый проект';}
function ProjectCard({job,onOpen,promotion}:{job:JobInfo;onOpen:(id:string,promo?:boolean)=>void;promotion:boolean}) {
 const status=job.pipeline_status==='running'?'Обрабатывается':job.pipeline_status==='failed'?'Нужно внимание':job.has_assembly?'Урок готов':'В работе';
 return <button className="project-tile" onClick={()=>onOpen(job.job_id,promotion)}>
   <div className={`project-cover ${job.has_assembly?'complete':''}`}>
     <div className="project-cover-fallback" aria-hidden="true"><div className="fallback-window"><i/><i/><i/><span><StudioIcon name="play"/></span></div></div>
     <img className="project-cover-image" src={`${API}/jobs/${job.job_id}/artifacts/brand_intro.png`} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none'; }}/>
     <span className="project-format">ВИДЕОУРОК</span><span className="project-play"><StudioIcon name="play"/></span><span className={`project-status ${job.pipeline_status==='failed'?'attention':''}`}>{status}</span>
   </div>
   <div className="project-tile-body"><span className="project-avatar" aria-hidden="true">L</span><div className="project-info"><h3>{job.display_name}</h3><small>{projectDate(job.job_id)} · {promotion?'Основа для коротких роликов':status}</small><span className="project-open">{promotion?'Создать ролики':job.has_assembly?'Открыть видео':'Продолжить работу'}<StudioIcon name="arrow"/></span></div></div>
 </button>;
}
export default function StudioHome({view,jobs,busy,query,onQueryChange,onNavigate,onOpen}:{view:StudioView;jobs:JobInfo[];busy:boolean;query:string;onQueryChange:(value:string)=>void;onNavigate:(v:StudioView)=>void;onOpen:(id:string,promo?:boolean)=>void}) {
 const [filter,setFilter]=useState('all');
 const promotion=view==='promotion';
 const sorted=[...jobs].sort((a,b)=>(b.job_id.match(/job_(\d{8}_\d{6})/)?.[1] || '').localeCompare(a.job_id.match(/job_(\d{8}_\d{6})/)?.[1] || ''));
 const candidates=promotion?sorted.filter(j=>j.has_assembly):sorted;
 const visible=candidates.filter(j=>(filter==='all'||(filter==='ready'?j.has_assembly:!j.has_assembly))&&`${j.display_name} ${j.job_id}`.toLowerCase().includes(query.toLowerCase()));
 const isHome=view==='home';
 return <div className="studio-home">
  {isHome ? <>
    <div className="home-heading"><div className="eyebrow">ВИДЕОСТУДИЯ ДЛЯ ЗАПИСЕЙ ЭКРАНА</div><h1>Из записи экрана — в видео,<br/>которое хочется смотреть.</h1><p>Создавайте уроки с озвучкой и субтитрами, а затем короткие ролики для продвижения — без новой съёмки.</p></div>
    <div className="home-categories" aria-label="Разделы студии"><button className="active" onClick={()=>onNavigate('home')}>Для вас</button><button onClick={()=>onNavigate('projects')}>Мои видеоуроки</button><button onClick={()=>onNavigate('promotion')}>Короткие ролики</button></div>
    <section className="creation-hero" aria-label="Создание видеоурока"><div className="hero-copy"><span className="hero-kicker">ВАША ЗАПИСЬ — ГЛАВНЫЙ МАТЕРИАЛ</span><h2>Записали экран?<br/>Luka соберёт урок.</h2><p>Очистит речь, добавит озвучку, субтитры, выделения и заставки. Готовый урок останется основой для роликов на разных площадках.</p><button className="hero-button" onClick={()=>onNavigate('new')}><StudioIcon name="plus"/>Создать видеоурок<StudioIcon name="arrow"/></button><small>Для блогеров, репетиторов и авторов курсов</small></div>
      <div className="hero-art" aria-hidden="true"><div className="art-orbit"/><div className="art-window"><div className="art-toolbar"><i/><i/><i/><span>ЗАПИСЬ ЭКРАНА → ВИДЕОУРОК</span></div><div className="art-content"><div className="art-menu"/><div className="art-document"><b>Ваш урок готов к просмотру</b><em/><em/><div className="art-highlight">Важный шаг выделен<span>↖</span></div><em/></div></div><div className="art-caption">Теперь зритель не пропустит главное</div><div className="art-timeline">{Array.from({length:24},(_,i)=><i key={i} style={{height:8+(i*7%19)}}/>)}</div><span className="hero-video-duration">08:16</span></div><span className="art-chip">● Готовый видеоурок</span><span className="art-short"><StudioIcon name="play"/><b>Ещё и ролик<br/>для Shorts</b><small>9:16</small></span></div>
    </section>
    <div className="home-workflow" aria-label="Как это работает">{[['01','Загрузите запись','Урок, разбор или обзор'],['02','Получите готовый урок','Посмотрите, утвердите, скачайте'],['03','Продвигайте свой контент','Shorts, Reels и VK Клипы']].map(([n,t,d])=><div key={n}><span>{n}</span><div><strong>{t}</strong><small>{d}</small></div></div>)}</div>
  </> : <div className="library-heading"><div className="eyebrow">{promotion?'ИЗ ГОТОВОГО УРОКА':'ВАША ВИДЕОБИБЛИОТЕКА'}</div><h1>{promotion?'Ролики для продвижения':'Мои видеоуроки'}</h1><p>{promotion?'Выберите готовый урок — из его записи Luka соберёт короткие версии для Shorts, Reels и VK Клипов.':'Все записи, уроки и результаты обработки в одном месте.'}</p><div className="home-categories" aria-label="Разделы студии"><button onClick={()=>onNavigate('home')}>Для вас</button><button className={!promotion?'active':''} onClick={()=>onNavigate('projects')}>Мои видеоуроки</button><button className={promotion?'active':''} onClick={()=>onNavigate('promotion')}>Короткие ролики</button></div></div>}
  <section className="projects-section" aria-label="Проекты"><div className="projects-heading"><h2>{isHome?'Продолжить просмотр и работу':promotion?'Выберите видеоурок':'Все видеоуроки'} <span>{candidates.length}</span></h2>{isHome&&<button className="text-action" onClick={()=>onNavigate('projects')}>Смотреть все <StudioIcon name="arrow"/></button>}</div>
    {!isHome&&<div className="library-tools">{query&&<div className="search-summary">Поиск: «{query}» <button onClick={()=>onQueryChange('')}>Сбросить</button></div>}{!promotion&&<div className="project-filters" aria-label="Статус проекта">{[['all','Все'],['ready','Готовые'],['working','В работе']].map(([id,label])=><button key={id} aria-pressed={filter===id} className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div>}</div>}
    {busy?<div className="library-empty" role="status">Загружаем ваши проекты…</div>:visible.length?<div className="project-grid">{(isHome?visible.slice(0,3):visible).map(job=><ProjectCard key={job.job_id} job={job} onOpen={onOpen} promotion={promotion}/>)}</div>:<div className="library-empty"><StudioIcon name="film"/><h3>{query?'Ничего не найдено':promotion?'Сначала подготовьте видеоурок':'Здесь появятся ваши проекты'}</h3><p>{query?'Попробуйте другое название.':promotion?'Готовый урок станет основой для коротких роликов.':'Загрузите запись экрана — уроки и рекламные ролики будут собраны здесь.'}</p>{!query&&<button className="btn-primary" onClick={()=>onNavigate(promotion?'projects':'new')}>{promotion?'Перейти к проектам':'Создать первый видеоурок'}</button>}</div>}
  </section>
  {isHome&&<button className="promotion-banner" onClick={()=>onNavigate('promotion')}><span className="promo-icon"><StudioIcon name="promotion"/></span><span><strong>Один урок — ролики для каждой площадки</strong><small>Возьмём подходящие фрагменты вашей записи и подготовим короткие версии для продвижения.</small></span><span className="platform-pills"><i>Shorts</i><i>Reels</i><i>VK Клипы</i></span><StudioIcon name="arrow"/></button>}
  {isHome&&<footer className="home-footer"><span>Объясняйте свою тему. Делитесь знаниями. Развивайте аудиторию.</span><span>Исходная запись остаётся основой вашего видео.</span></footer>}
 </div>;
}
