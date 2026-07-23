import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRevalidator } from 'react-router-dom';

import WebSocketClient from '@/classes/WebsocketClient';

import useMe from './useMe';

export interface TaskSampleUser {
  user_id: number;
  username: string;
  task_id: number;
  sample_id: number;
}

export default function useSampleWs() {
  const routeParams = useParams();
  const revalidator = useRevalidator();
  const me = useMe();
  const [connections, setConnections] = useState<TaskSampleUser[]>([]);
  const host = window.location.host;
  const token = localStorage.getItem('token')?.split(' ')[1];
  const wsRef = useRef<WebSocketClient | null>(null);
  const revalidateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sampleId = Number(routeParams.sampleId);
  const latestSampleIdRef = useRef(sampleId);
  latestSampleIdRef.current = sampleId;

  useEffect(() => {
    if (!wsRef.current) {
      return;
    }

    const isMeCurrentEditor = connections.find((item) => item.sample_id === sampleId)?.user_id === me.data?.id;
    const ws = wsRef.current;
    const handleSampleUpdate = (data: TaskSampleUser) => {
      if (!isMeCurrentEditor && data.user_id !== me.data?.id && data.sample_id === sampleId) {
        if (revalidateTimerRef.current) {
          clearTimeout(revalidateTimerRef.current);
        }
        revalidateTimerRef.current = setTimeout(() => {
          revalidator.revalidate();
          revalidateTimerRef.current = null;
        }, 100);
      }
    };

    ws.on('update', handleSampleUpdate);

    return () => {
      ws.off('update', handleSampleUpdate);
      if (revalidateTimerRef.current) {
        clearTimeout(revalidateTimerRef.current);
        revalidateTimerRef.current = null;
      }
    };
  }, [connections, me.data?.id, revalidator, sampleId]);

  useEffect(() => {
    wsRef.current = new WebSocketClient(
      `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${host}/ws/task/${routeParams.taskId}/${
        latestSampleIdRef.current
      }?token=${token}`,
    );

    const ws = wsRef.current;

    ws.on('peers', (data) => {
      setConnections(data);
    });

    return () => {
      ws.destroy();
      wsRef.current = null;
    };
  }, [host, routeParams.taskId, token]);

  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || !sampleId) {
      return;
    }

    const syncSample = () => ws.send('sample', { sample_id: sampleId });
    ws.on('connect', syncSample);
    syncSample();

    return () => {
      ws.off('connect', syncSample);
    };
  }, [sampleId]);

  const currentSampleUsers = useMemo(() => {
    return connections.filter((item) => item.sample_id === sampleId);
  }, [connections, sampleId]);

  return [currentSampleUsers, connections];
}
