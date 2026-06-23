import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

type Props = {
  data: number[];
  labels?: string[];
  color: string;
  height?: number;
  target?: number;
  unit?: string;
  fill?: boolean;
};

export default function LineChart({
  data, labels, color, height = 80, target, unit, fill = true,
}: Props) {
  if (!data.length) return null;
  const maxVal = Math.max(...data, target || 0, 1);
  const padTop = 6;
  const padBottom = 18;
  const plotH = height - padTop - padBottom;
  const stepX = 100 / Math.max(data.length - 1, 1);

  const points = data.map((v, i) => ({
    x: i * stepX,
    y: padTop + (1 - v / maxVal) * plotH,
  }));

  const segments: Array<{ x1: number; y1: number; x2: number; y2: number; len: number; angle: number }> = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const dx = (p2.x - p1.x) * 3.2;
    const dy = p2.y - p1.y;
    const len = Math.sqrt(dx * dx + dy * dy);
    const angle = Math.atan2(dy, dx) * (180 / Math.PI);
    segments.push({ x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, len, angle });
  }

  const targetY = target != null && target > 0 ? padTop + (1 - target / maxVal) * plotH : null;

  return (
    <View style={[styles.wrap, { height }]}>
      {targetY != null && (
        <View style={[styles.targetLine, { top: targetY }]} pointerEvents="none" />
      )}
      {fill && (
        <View
          style={[
            styles.area,
            {
              backgroundColor: color + '15',
              bottom: padBottom,
              top: padTop,
            },
          ]}
          pointerEvents="none"
        />
      )}
      {segments.map((s, i) => (
        <View
          key={'s' + i}
          style={[
            styles.seg,
            {
              left: `${s.x1}%`,
              top: s.y1,
              width: s.len,
              transform: [{ rotate: `${s.angle}deg` }],
              backgroundColor: color,
            },
          ]}
          pointerEvents="none"
        />
      ))}
      {points.map((p, i) => (
        <View
          key={'p' + i}
          style={[styles.dot, { left: `${p.x}%`, top: p.y, borderColor: color }]}
          pointerEvents="none"
        >
          <View style={[styles.dotInner, { backgroundColor: color }]} />
        </View>
      ))}
      {(labels ?? []).map((d, i) => (
        <Text key={'l' + i} style={[styles.label, { left: `${i * stepX}%` }]}>
          {d}
        </Text>
      ))}
      {data.map((v, i) => (
        <Text
          key={'v' + i}
          style={[
            styles.value,
            { color, left: `${i * stepX}%`, top: points[i].y - 18 },
          ]}
        >
          {v > 0 ? `${v}` : ''}
        </Text>
      ))}
      {target != null && (
        <Text style={[styles.targetLabel, { color }]}>{target}{unit || ''} 目标</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'relative', marginHorizontal: 4 },
  seg: {
    position: 'absolute', height: 2, marginLeft: 0, marginTop: -1,
    borderRadius: 1, transformOrigin: 'left center',
  },
  dot: {
    position: 'absolute', width: 12, height: 12, borderRadius: 6,
    marginLeft: -6, marginTop: -6, borderWidth: 2, backgroundColor: '#fff',
  },
  dotInner: {
    position: 'absolute', top: 2, left: 2, right: 2, bottom: 2, borderRadius: 4,
  },
  label: {
    position: 'absolute', bottom: 2, fontSize: 10, color: '#b8ad9e',
    marginLeft: -6, width: 16, textAlign: 'center',
  },
  value: {
    position: 'absolute', fontSize: 10, fontWeight: '600',
    marginLeft: -10, width: 20, textAlign: 'center',
  },
  targetLine: {
    position: 'absolute', left: 0, right: 0, height: 1,
    backgroundColor: 'rgba(0,0,0,0.12)', borderStyle: 'dashed',
  },
  targetLabel: {
    position: 'absolute', right: 0, top: 0, fontSize: 9, fontWeight: '500',
  },
  area: {
    position: 'absolute', left: 0, right: 0, borderRadius: 8,
  },
});