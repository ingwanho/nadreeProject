const {before, after, test} = require('node:test');
const fs = require('node:fs');
const {initializeTestEnvironment, assertSucceeds, assertFails} = require('@firebase/rules-unit-testing');
const {doc, setDoc, getDoc, getDocs, collection, query, where, Timestamp} = require('firebase/firestore');
let env;
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
