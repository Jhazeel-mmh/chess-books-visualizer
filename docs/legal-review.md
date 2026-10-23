# Revisión legal: puntos para el abogado

Borradores del 21 de octubre de 2026, para revisar antes de abrir el sitio. Los textos están en
`frontend/src/policies/` (`terms`, `privacy`, `copyright`; `.es.md` es la versión que prevalece,
`.en.md` su traducción) y se ven en el sitio en `/terms`, `/privacy` y `/copyright/policy`. Lo que
va entre llaves (`{operator}`, `{strikes}`…) lo llena el sitio con su configuración y con las reglas
del código.

Qué es el sitio: cada persona sube sus propios libros de ajedrez (PDF o EPUB) a una biblioteca
privada; el sitio lee en ellos jugadas y diagramas y se los muestra junto a la página original.
Nada se comparte entre usuarios. Tiene un plan gratuito, con anuncios en las páginas que no
muestran ningún libro, y un plan de pago, Plus (más libros y espacio, entrenamiento diario sin límite
y sin anuncios), que vende Paddle. Opera desde México. Los planes se ven en `/plans`.

## 1. Responsable

- ¿Persona física o moral? ¿Qué domicilio publicar (el aviso de privacidad pide «identidad y
  domicilio»)?

## 2. Aviso de privacidad (LFPDPPP de 2025)

- Tratamos las finalidades como necesarias para la relación jurídica, sin consentimiento aparte.
  ¿Es correcto para todas, incluida la seguridad (límite de intentos por dirección IP, en memoria,
  una hora)?
- Plazos ARCO: escribimos 20 días hábiles para responder y 15 para hacerlo efectivo, y la Secretaría
  Anticorrupción y Buen Gobierno como autoridad. Confirmar con el texto vigente.
- Proveedores (alojamiento y correo, posiblemente fuera de México): ¿hay que nombrarlos? ¿Algo más
  para una remisión internacional?
- ¿Basta el aviso integral publicado y enlazado al registrarse, o hace falta además un aviso
  simplificado en el formulario?
- Conservación: los avisos, contraavisos y amonestaciones se guardan aunque se borre la cuenta,
  «mientras sean necesarios». ¿Qué plazo fijar?

## 3. Términos de uso

- Edad mínima 13 años, y de 13 a 17 con permiso de madre, padre o tutor. ¿Es válido en México, o
  conviene 18 (o 16)?
- La aceptación es una casilla obligatoria al registrarse; el servidor rechaza el registro sin ella
  y guarda la fecha de alta, no la versión aceptada. ¿Es suficiente?
- Limitación de responsabilidad frente a la Ley Federal de Protección al Consumidor.
- Jurisdicción: tribunales del domicilio del responsable, sin perjuicio de PROFECO. ¿Hace falta
  nombrar la ciudad?
- Aviso de cambios importantes con 15 días de anticipación, y de cierre del servicio con 30.

## 4. Derechos de autor (LFDA art. 114 Octies y su Reglamento)

- El Reglamento reformado (DOF 24 de septiembre de 2026, en vigor a los 90 días hábiles) pide un
  formulario «claro y accesible». ¿Cumple el nuestro (`/copyright`)?
- Restablecimiento tras un contraaviso: 15 días hábiles desde que se lo enviamos a quien presentó el
  aviso, salvo que acredite un procedimiento judicial o administrativo, una denuncia penal o un
  mecanismo alterno. Contamos días hábiles sin fines de semana ni los días de descanso obligatorio de
  la LFT (art. 74). ¿Es el cómputo correcto? La DMCA pide 10 a 14 días hábiles: elegimos la ley
  mexicana.
- El contraaviso incluye la aceptación de la jurisdicción federal de EE. UU. que pide la DMCA.
  ¿Conviene mantenerla para un sitio mexicano?
- Política de reincidencia: la cuenta se cierra con 3 amonestaciones, contadas por correo
  electrónico. ¿Razonable?

## 5. Estados Unidos y Europa

- DMCA: ¿conviene registrar un agente en la Copyright Office (US$6 por 3 años) siendo un operador
  mexicano? Sus datos se publican en la política (`CBV_COPYRIGHT_AGENT`).
- RGPD: bases legales, y si hace falta un representante en la UE (art. 27).
- DSA: ¿punto de contacto (arts. 11 y 12) o representante legal (art. 13)?

## 6. Plus y Paddle (términos, apartado 3)

- Plus lo vende Paddle como comerciante registrado (merchant of record): Paddle le cobra y le factura
  al comprador, con los impuestos de su país, y nos paga a nosotros. ¿Qué hace falta en México para
  recibir esos pagos (RFC, régimen, comprobantes; ¿exportación de servicios?)? Pregunta para el
  contador, pero el abogado puede confirmar que el modelo es válido frente a la LFPC.
- Renovación automática al mismo precio; aviso por correo con 15 días de anticipación si cambia el
  precio o lo que da Plus; cancelación con un botón en la cuenta, efectiva al final del periodo
  pagado. ¿Cumple la LFPC (cancelar tan fácil como contratar) y lo que pide PROFECO?
- Al borrar la cuenta, o si la cerramos por infracciones, la suscripción se cancela en ese momento,
  sin reembolso del resto del periodo. Si cerramos el servicio, prometemos reembolso proporcional.
  ¿Debe haberlo también en los otros casos? Los reembolsos los atiende Paddle según sus términos
  para compradores (14 días de desistimiento en la UE y el Reino Unido).
- Plus solo para mayores de edad o con permiso de madre, padre o tutor. ¿Basta así?
- Plus da más espacio para libros. ¿Cobrar por espacio puede verse como un beneficio económico
  directo de las infracciones de los usuarios, que haría perder la protección de la LFDA (art. 114
  Octies) o de la DMCA (§ 512(c)(1)(B))? En EE. UU. una cuota fija por el servicio no suele
  contarse así, pero conviene confirmarlo. Los anuncios nunca están junto al contenido de un libro.

## 7. Anuncios (aviso de privacidad, apartados 3, 4, 6 y 8)

- Tratamos los anuncios como finalidad secundaria. La LFPDPPP pide un medio para negarse antes del
  tratamiento: hoy lo son la configuración de anuncios de Google, bloquear las cookies de terceros
  o contratar Plus. ¿Basta, o hace falta una casilla propia (por ejemplo, al registrarse)?
- Google recaba los datos directamente del navegador, como responsable por su cuenta. ¿Es eso una
  transferencia nuestra que requiera consentimiento?
- Para el EEE, el Reino Unido y Suiza usamos el mensaje de consentimiento de Google (una CMP
  certificada). ¿Hace falta algo más para el RGPD o la directiva ePrivacy?
- Paddle recibe el correo y un identificador de la cuenta para relacionar el pago: lo tratamos
  como necesario para el contrato, sin consentimiento. ¿Correcto?
