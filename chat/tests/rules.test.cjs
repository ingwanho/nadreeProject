const {before, after, test} = require('node:test');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {initializeTestEnvironment, assertSucceeds, assertFails} = require('@firebase/rules-unit-testing');
const {doc, setDoc, getDoc, getDocs, collection, query, where, Timestamp, orderBy, documentId, limit, startAfter, writeBatch} = require('firebase/firestore');
let env;
const indexedRooms = [];
before(async () => {
  env = await initializeTestEnvironment({projectId: 'demo-nadree-chat', firestore: {rules: fs.readFileSync('firestore.rules', 'utf8')}});
  await env.withSecurityRulesDisabled(async context => {
    const db = context.firestore();
    for (const uid of ['customer', 'other', 'primary', 'staff']) {
      await setDoc(doc(db, 'chatUsers', uid), {active: true, sessionId: 'sid', expiresAt: Timestamp.fromMillis(Date.now() + 3600000)});
    }
    for (const uid of ['primary', 'staff']) {
      await setDoc(doc(db, 'chatShops/shop/members', uid), {active: true, canReply: uid === 'primary'});
    }
    await setDoc(doc(db, 'chatRoomAccess/room'), {customerUid: 'customer', shopId: 'shop', status: 'open'});
    await setDoc(doc(db, 'chatRoomAccess/room/messages/message'), {text: 'test'});
    const batch = writeBatch(db);
    for (const kind of ['booking', 'inquiry']) {
      for (const status of ['open', 'read_only']) {
        for (let i = 0; i < 110; i++) {
          const id = `index-${kind}-${status}-${String(i).padStart(3, '0')}`;
          const at = i < 55 ? 1700000000000 : null;
          indexedRooms.push({id, kind, status, at});
          batch.set(doc(db, 'chatRoomAccess', id), {customerUid: 'customer', shopId: 'shop', kind, status,
            lastMessageAt: at === null ? null : Timestamp.fromMillis(at), updatedAt: Timestamp.fromMillis(i)});
        }
      }
    }
    batch.set(doc(db, 'chatRoomAccess/foreign-index-room'), {customerUid: 'other', shopId: 'foreign-shop',
      kind: 'booking', status: 'open', lastMessageAt: Timestamp.fromMillis(1800000000000)});
    await batch.commit();
  });
});
after(async () => { await env.cleanup(); });
const db = uid => env.authenticatedContext(uid, {chatSessionId: 'sid'}).firestore();
test('customer and direct staff may read, unrelated user may not', async () => {
  for (const uid of ['customer', 'primary', 'staff']) await assertSucceeds(getDoc(doc(db(uid), 'chatRoomAccess/room/messages/message')));
  await assertFails(getDoc(doc(db('other'), 'chatRoomAccess/room/messages/message')));
});
test('all client message writes and membership changes are denied', async () => {
  for (const uid of ['customer', 'primary', 'staff']) await assertFails(setDoc(doc(db(uid), 'chatRoomAccess/room/messages/new'), {text: 'forbidden'}));
  await assertFails(setDoc(doc(db('staff'), 'chatShops/shop/members/staff'), {active: true, canReply: true}));
});
test('list queries must constrain customer or direct shop', async () => {
  await assertSucceeds(getDocs(query(collection(db('customer'), 'chatRoomAccess'), where('customerUid', '==', 'customer'))));
  await assertSucceeds(getDocs(query(collection(db('staff'), 'chatRoomAccess'), where('shopId', '==', 'shop'))));
  await assertFails(getDocs(collection(db('other'), 'chatRoomAccess')));
});
test('wrong session and missing auth are denied', async () => {
  const old = env.authenticatedContext('customer', {chatSessionId: 'old'}).firestore();
  await assertFails(getDoc(doc(old, 'chatRoomAccess/room')));
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), 'chatRoomAccess/room')));
});

function managerQuery(database, shop, kind, status, last) {
  const filters = [where('shopId', '==', shop)];
  if (kind) filters.push(where('kind', '==', kind));
  if (status) filters.push(where('status', '==', status));
  filters.push(orderBy('lastMessageAt', 'desc'), orderBy(documentId(), 'desc'), limit(50));
  if (last) filters.push(startAfter(last.get('lastMessageAt'), last.id));
  return query(collection(database, 'chatRoomAccess'), ...filters);
}

test('manager last-message pages preserve equal and null timestamps for all nine filters', async t => {
  for (const uid of ['primary', 'staff']) {
    for (const kind of [null, 'booking', 'inquiry']) {
      for (const status of [null, 'open', 'read_only']) {
        await t.test(`${uid}: ${kind || 'all'} / ${status || 'all'}`, async () => {
          const expected = indexedRooms.filter(room => (!kind || room.kind === kind) && (!status || room.status === status))
            .sort((a, b) => {
              if (a.at !== b.at) return a.at === null ? 1 : b.at === null ? -1 : b.at - a.at;
              return a.id > b.id ? -1 : a.id < b.id ? 1 : 0;
            }).map(room => room.id);
          const ids = [];
          let last;
          while (true) {
            const page = await assertSucceeds(getDocs(managerQuery(db(uid), 'shop', kind, status, last)));
            assert.ok(page.size <= 50);
            if (page.empty) break;
            ids.push(...page.docs.map(item => item.id));
            assert.equal(new Set(ids).size, ids.length, 'cursor repeated a document');
            assert.ok(ids.length <= expected.length, 'cursor did not advance');
            last = page.docs.at(-1);
          }
          assert.deepEqual(ids, expected, 'missing lastMessageAt fields stay excluded; null values remain included');
        });
      }
    }
  }
});

test('manager last-message filters retain direct-shop and session access checks', async () => {
  for (const uid of ['primary', 'staff']) {
    for (const kind of [null, 'booking', 'inquiry']) {
      for (const status of [null, 'open', 'read_only']) {
        await assertFails(getDocs(managerQuery(db(uid), 'foreign-shop', kind, status)));
      }
    }
    await assertFails(getDocs(query(collection(db(uid), 'chatRoomAccess'), orderBy('lastMessageAt', 'desc'), limit(50))));
  }
  await assertFails(getDocs(managerQuery(db('other'), 'shop', null, null)));
  await assertFails(getDocs(managerQuery(env.unauthenticatedContext().firestore(), 'shop', null, null)));
  const old = env.authenticatedContext('primary', {chatSessionId: 'old'}).firestore();
  await assertFails(getDocs(managerQuery(old, 'shop', null, null)));
});
