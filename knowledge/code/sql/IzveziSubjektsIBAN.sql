SELECT 
--S.*, 
S.anQid,
S.acSubject,
S.acName2,
S.acName3,
S.acAddress,
S.acPost,
S.acCity,
S.acCountry,
S.acBuyer,
S.acSupplier,
S.acPIN,
S.acCode,
	Case
		when IsNull(SSB.acBnkAcctNo1, '') = '' then ''
		else Coalesce(NullIf(RTrim(SC.acISOCode), ''), RTrim(cOur.acIsoCode))
		+ dbo.fHR_CalcContrMod97(Replace(SSB.acBnkAcctNo1, ' ', '') + Coalesce(NullIf(RTrim(SC.acISOCode), ''), RTrim(cOur.acIsoCode)) + '00')
		+ Replace(SSB.acBnkAcctNo1, ' ', '') 
	end As acIBAN
--S.acCity AS PostaKraj, B.acBnkAcctNo1, B.acBnkAcctNo2, B.acBnkAcctNo3, B.acBank as RacunBanka, S.anQId as anQIdGDPRLogS
FROM 
	vHE_SetSubj S                        
	LEFT JOIN tHE_SetSubjBank SSB ON SSB.acSubject = S.acSubject 	
	LEFT join tHE_SetCountry SC ON S.acCountry = SC.acCountry
	CROSS JOIN tPA_SysParam SP
	LEFT JOIN tHE_SetCountry COur ON COur.acCountry = SP.acCountry
WHERE 
1=1
--and S.acSubject LIKE '%0812%' 
AND S.acSubject <> '' 
and S.acActive = 'T'
AND (
    S.acBuyer = 'T'
    OR S.acSupplier = 'T'
)
ORDER BY S.acSubject
