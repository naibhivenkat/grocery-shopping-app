package com.example.groceryshoppingapp.models

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

@Parcelize
data class AppUser(
    val id: String = "",            // Firestore doc id
    val customerId: String? = null, // This is the one used in khata
    val fullName: String = "",
    val phone: String = "",
    val role: String = ""
) : Parcelable
